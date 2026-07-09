import logging
import base64
from email.mime.text import MIMEText
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models.google_credentials import GoogleCredentials
from app.models.lead import Lead

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


async def exchange_authorization_code(code: str) -> dict:
    payload = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": "http://localhost:8080/api/integrations/gmail/callback",
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data=payload)
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> str:
    payload = {
        "refresh_token": refresh_token,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["access_token"]


async def send_email_on_behalf_of_user(
    db: AsyncSession,
    user_id: UUID,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    result = await db.execute(
        select(GoogleCredentials).where(GoogleCredentials.user_id == user_id)
    )
    creds = result.scalar_one_or_none()
    if not creds:
        raise RuntimeError(f"No Google credentials found for user {user_id}")

    access_token = await refresh_access_token(creds.refresh_token)

    message = MIMEText(body, "plain")
    message["To"] = recipient
    message["Subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GMAIL_SEND_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
        )
        resp.raise_for_status()


async def send_email_in_background(
    user_id: UUID,
    lead_id: UUID,
    subject: str,
    body: str,
) -> None:
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Lead).where(Lead.id == lead_id)
            )
            lead = result.scalar_one_or_none()
            if not lead or not lead.email:
                logger.warning(f"Lead {lead_id} not found or has no email")
                return

            await send_email_on_behalf_of_user(
                db, user_id, lead.email, subject, body,
            )
            logger.info(f"Gmail sent to {lead.email} for user {user_id}")
    except Exception as e:
        logger.error(f"Background Gmail send failed for user {user_id}: {e}")
