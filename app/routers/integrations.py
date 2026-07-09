import logging

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.models.google_credentials import GoogleCredentials
from app.services.gmail_service import exchange_authorization_code
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/gmail/auth-url")
async def gmail_auth_url(current_user: User = Depends(get_current_user)):
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": "http://localhost:8080/api/integrations/gmail/callback",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/gmail.send",
        "access_type": "offline",
        "prompt": "consent",
        "state": str(current_user.id),
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"
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

    google_email = token_data.get("email", "")

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
        url=f"{settings.frontend_origins[0]}/dashboard?integration=success",
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
