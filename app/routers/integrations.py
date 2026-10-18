import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.crypto import decrypt_key, encrypt_key
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.models.google_credentials import GoogleCredentials
from app.models.google_calendar_credentials import GoogleCalendarCredentials
from app.services.google_calendar_service import (
    begin_calendar_oauth, consume_calendar_oauth, calendar_callback_url,
    exchange_calendar_code, save_calendar_credentials,
)
from app.services.gmail_service import (
    begin_gmail_oauth,
    consume_gmail_oauth,
    exchange_authorization_code,
    fetch_google_email,
    google_refresh_token,
    revoke_google_token,
)
from app.config import settings
from app.middleware.rate_limit import OAUTH_FLOW, rate_limit


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/google-calendar/auth-url", dependencies=[Depends(rate_limit(OAUTH_FLOW, "user"))])
async def google_calendar_auth_url(response: Response, current_user: User = Depends(get_current_user)):
    state, binding = begin_calendar_oauth(current_user.id)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": calendar_callback_url(),
        "response_type": "code",
        "scope": "openid email https://www.googleapis.com/auth/calendar.events",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    response.set_cookie("calendar_oauth_binding", binding, max_age=600, httponly=True, secure=settings.app_env.lower() != "development", samesite="lax", path="/integrations/google-calendar")
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "data": {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}}


@router.get("/google-calendar/callback", dependencies=[Depends(rate_limit(OAUTH_FLOW, "ip"))])
async def google_calendar_callback(request: Request, state: str = "", code: str = "", db: AsyncSession = Depends(get_db)):
    user_id = consume_calendar_oauth(state, request.cookies.get("calendar_oauth_binding"))
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    try:
        await save_calendar_credentials(db, user_id, await exchange_calendar_code(code))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Google Calendar authorization failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google Calendar connection failed") from exc
    response = RedirectResponse(settings.oauth_frontend_url.rstrip("/") + "/settings?calendar=connected", status_code=303)
    response.delete_cookie("calendar_oauth_binding", path="/integrations/google-calendar")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/google-calendar/status")
async def google_calendar_status(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record = (await db.execute(select(GoogleCalendarCredentials).where(GoogleCalendarCredentials.user_id == current_user.id))).scalar_one_or_none()
    return {"success": True, "data": {"connected": record is not None, "email": record.google_email if record else None}}


@router.delete("/google-calendar")
async def disconnect_google_calendar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = (
        await db.execute(
            select(GoogleCalendarCredentials).where(
                GoogleCalendarCredentials.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if record is not None:
        try:
            await revoke_google_token(decrypt_key(record.encrypted_refresh_token))
        except Exception:
            logger.warning(
                "Google Calendar token revocation failed for user %s; deleting local credentials",
                current_user.id,
            )
        await db.delete(record)
        await db.commit()
    return {"success": True, "message": "Google Calendar disconnected", "data": {}}


def gmail_success_redirect_url() -> str:
    """Return users to the canonical frontend, never a temporary CORS origin."""
    return f"{settings.oauth_frontend_url.rstrip('/')}/settings?integration=success"


@router.get("/gmail/auth-url", dependencies=[Depends(rate_limit(OAUTH_FLOW, "user"))])
async def gmail_auth_url(response: Response, current_user: User = Depends(get_current_user)):
    try:
        state, binding = begin_gmail_oauth(current_user.id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.backend_url}/integrations/gmail/callback",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly openid email",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    response.set_cookie("gmail_oauth_binding", binding, max_age=600, httponly=True, secure=settings.app_env.lower() != "development", samesite="lax", path="/integrations/gmail")
    response.headers["Cache-Control"] = "no-store"
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return {"success": True, "data": {"url": url}}


@router.get("/gmail/callback", dependencies=[Depends(rate_limit(OAUTH_FLOW, "ip"))])
async def gmail_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        user_id = consume_gmail_oauth(state, request.cookies.get("gmail_oauth_binding"))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

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
        existing.encrypted_refresh_token = encrypt_key(refresh_token)
        existing.google_email = google_email
    else:
        creds = GoogleCredentials(
            user_id=user_id,
            google_email=google_email,
            encrypted_refresh_token=encrypt_key(refresh_token),
        )
        db.add(creds)

    await db.commit()

    response = RedirectResponse(
        url=gmail_success_redirect_url(),
        status_code=302,
    )
    response.delete_cookie("gmail_oauth_binding", path="/integrations/gmail")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


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


@router.delete("/gmail")
async def disconnect_gmail(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GoogleCredentials).where(GoogleCredentials.user_id == current_user.id)
    )
    credentials = result.scalar_one_or_none()
    if credentials is not None:
        try:
            await revoke_google_token(google_refresh_token(credentials))
        except Exception:
            logger.warning(
                "Gmail token revocation failed for user %s; deleting local credentials",
                current_user.id,
            )
        await db.delete(credentials)
        await db.commit()
    return {"success": True, "message": "Gmail disconnected", "data": {}}
