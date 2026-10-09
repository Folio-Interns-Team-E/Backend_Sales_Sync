import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.core.crypto import decrypt_key
from app.middleware.auth_middleware import get_current_user, get_team_context, TeamContext
from app.models.team_member import MemberRole, TeamMember
from app.models.user import User
from app.models.google_credentials import GoogleCredentials
from app.services.gmail_service import exchange_authorization_code, fetch_google_email
from app.config import settings
from app.schemas.common import ApiResponse
from app.schemas.calcom import CalComIntegrationCreate, CalComIntegrationResponse, CalComStatus, CalComEventTypeUpdate
from app.services.calcom_service import (
    begin_calcom_oauth, consume_calcom_oauth, exchange_calcom_code, get_calcom_integration,
    oauth_access_token, save_calcom_oauth, save_or_update_calcom, verify_calcom_credentials,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


def gmail_success_redirect_url() -> str:
    """Return users to the canonical frontend, never a temporary CORS origin."""
    return f"{settings.oauth_frontend_url.rstrip('/')}/settings?integration=success"


@router.get("/gmail/auth-url")
async def gmail_auth_url(current_user: User = Depends(get_current_user)):
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.backend_url}/integrations/gmail/callback",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/gmail.send openid email",
        "access_type": "offline",
        "prompt": "consent",
        "state": str(current_user.id),
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return {"success": True, "data": {"url": url}}


@router.get("/gmail/callback")
async def gmail_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        user_id = UUID(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        token_data = await exchange_authorization_code(code)
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to exchange authorization code")

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh_token returned; ensure access_type=offline and prompt=consent")

    access_token = token_data.get("access_token", "")
    google_email = await fetch_google_email(access_token) if access_token else ""

    result = await db.execute(
        select(GoogleCredentials).where(GoogleCredentials.user_id == user_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.refresh_token = refresh_token
        existing.google_email = google_email
    else:
        creds = GoogleCredentials(
            user_id=user_id,
            google_email=google_email,
            refresh_token=refresh_token,
        )
        db.add(creds)

    await db.commit()

    return RedirectResponse(
        url=gmail_success_redirect_url(),
        status_code=302,
    )


@router.get("/gmail/status")
async def gmail_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GoogleCredentials).where(GoogleCredentials.user_id == current_user.id)
    )
    creds = result.scalar_one_or_none()
    return {
        "success": True,
        "data": {
            "connected": creds is not None,
            "email": creds.google_email if creds else None,
        },
    }



@router.get("/calcom/status", response_model=ApiResponse[CalComStatus])
async def calcom_status(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    integration = await get_calcom_integration(db, team_ctx.team_id)
    return ApiResponse(success=True, message="Cal.com status", data=CalComStatus(connected=integration is not None, event_type_id=integration.event_type_id if integration else None, needs_event_type=bool(integration and not integration.event_type_id)))


@router.post("/calcom/oauth/start")
async def start_calcom_oauth(response: Response, current_user: User = Depends(get_current_user), team_ctx: TeamContext = Depends(get_team_context)):
    if team_ctx.role not in {MemberRole.admin, MemberRole.manager}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can configure Cal.com")
    url, binding = begin_calcom_oauth(current_user.id, team_ctx.team_id)
    response.set_cookie("calcom_oauth_binding", binding, max_age=600, httponly=True, secure=settings.app_env.lower() != "development", samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "data": {"url": url}}


@router.get("/calcom/callback")
async def calcom_callback(request: Request, state: str = "", code: str = "", error: str = "", db: AsyncSession = Depends(get_db)):
    target = settings.oauth_frontend_url.rstrip("/")
    try:
        record = consume_calcom_oauth(state, request.cookies.get("calcom_oauth_binding"))
        if error or not code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cal.com authorization was cancelled")
        user_id, team_id = UUID(record["user_id"]), UUID(record["team_id"])
        membership = (await db.execute(select(TeamMember).where(TeamMember.user_id == user_id, TeamMember.team_id == team_id))).scalar_one_or_none()
        if not membership or membership.role not in {MemberRole.admin, MemberRole.manager}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace permission changed")
        await save_calcom_oauth(db, team_id, user_id, await exchange_calcom_code(code))
        response = RedirectResponse(target + "/settings?calcom=connected", status_code=303)
    except Exception:
        logger.warning("Cal.com OAuth callback failed")
        response = RedirectResponse(target + "/settings?calcom=failed", status_code=303)
    response.delete_cookie("calcom_oauth_binding", path="/")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.put("/calcom/event-type", response_model=ApiResponse[CalComStatus])
async def configure_calcom_event_type(payload: CalComEventTypeUpdate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    if team_ctx.role not in {MemberRole.admin, MemberRole.manager}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can configure Cal.com")
    integration = await get_calcom_integration(db, team_ctx.team_id)
    if not integration:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Cal.com first")
    token = await oauth_access_token(db, integration) if integration.credential_type == "oauth" else None
    await verify_calcom_credentials(token or decrypt_key(integration.encrypted_api_key), payload.event_type_id)
    integration.event_type_id = payload.event_type_id
    await db.commit()
    return ApiResponse(success=True, message="Cal.com event type saved", data=CalComStatus(connected=True, event_type_id=integration.event_type_id, needs_event_type=False))


@router.put("/calcom", response_model=ApiResponse[CalComIntegrationResponse], status_code=status.HTTP_200_OK)
async def save_integration(
    payload: CalComIntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    team_ctx: TeamContext = Depends(get_team_context),
):
    """
    Saves or updates the authenticated user's Cal.com integration configurations.
    """
    if team_ctx.role not in {MemberRole.admin, MemberRole.manager}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can configure Cal.com")
    integration = await save_or_update_calcom(db, team_ctx.team_id, current_user.id, payload.cal_api_key, payload.cal_event_type_id)
    
    # Map the model instance cleanly to our safe response schema
    response_data = CalComIntegrationResponse.model_validate(integration)
    
    return ApiResponse(
        success=True,
        message="Cal.com integration configured successfully.",
        data=response_data
    )


@router.delete("/calcom", response_model=ApiResponse[dict])
async def disconnect_calcom(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    if team_ctx.role not in {MemberRole.admin, MemberRole.manager}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can configure Cal.com")
    integration = await get_calcom_integration(db, team_ctx.team_id)
    if integration:
        await db.delete(integration)
        await db.commit()
    return ApiResponse(success=True, message="Cal.com disconnected", data={})
