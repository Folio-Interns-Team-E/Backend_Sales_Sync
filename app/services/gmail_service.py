import logging
import base64
import hashlib
import hmac
import json
import secrets
from email.mime.text import MIMEText
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import decrypt_key
from app.core.redis import get_redis
from app.database import SessionLocal
from app.models.google_credentials import GoogleCredentials
from app.models.lead import Lead
from app.models.email import Email

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def begin_gmail_oauth(user_id: UUID) -> tuple[str, str]:
    redis = get_redis()
    if redis is None:
        raise RuntimeError("Integration state service is unavailable")
    state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    redis.set(
        "gmail_oauth:" + _digest(state),
        json.dumps({"user_id": str(user_id), "binding": _digest(binding)}),
        ex=600,
        nx=True,
    )
    return state, binding


def consume_gmail_oauth(state: str, binding: str | None) -> UUID:
    if not state or len(state) > 128 or not binding:
        raise ValueError("Invalid Gmail authorization state")
    redis = get_redis()
    if redis is None:
        raise RuntimeError("Integration state service is unavailable")
    key = "gmail_oauth:" + _digest(state)
    raw = redis.get(key)
    if not raw:
        raise ValueError("Gmail authorization expired")
    record = json.loads(raw)
    if not hmac.compare_digest(record["binding"], _digest(binding)) or not redis.getdel(key):
        raise ValueError("Invalid Gmail authorization state")
    return UUID(record["user_id"])


def google_refresh_token(credentials: GoogleCredentials) -> str:
    return decrypt_key(credentials.encrypted_refresh_token)


async def exchange_authorization_code(code: str) -> dict:
    payload = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": f"{settings.backend_url}/integrations/gmail/callback",
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data=payload)
        resp.raise_for_status()
        return resp.json()


async def fetch_google_email(access_token: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json().get("email", "")


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


async def revoke_google_token(refresh_token: str) -> None:
    """Revoke a Google grant without placing the credential in a URL or log."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(GOOGLE_REVOKE_URL, data={"token": refresh_token})
        # A 400 response means the token is already invalid and cannot be used again.
        if response.status_code not in {200, 400}:
            response.raise_for_status()


async def search_gmail_messages(refresh_token: str, query: str, max_results: int = 10) -> list[dict]:
    access_token = await refresh_access_token(refresh_token)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GMAIL_MESSAGES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"q": query, "maxResults": max_results},
        )
        response.raise_for_status()
        return response.json().get("messages", [])


async def get_gmail_thread_id(refresh_token: str, message_id: str) -> str | None:
    access_token = await refresh_access_token(refresh_token)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GMAIL_MESSAGES_URL}/{message_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"format": "minimal"},
        )
        response.raise_for_status()
        return response.json().get("threadId")


async def send_email_on_behalf_of_user(
    db: AsyncSession,
    user_id: UUID,
    recipient: str,
    subject: str,
    body: str,
) -> str | None:
    result = await db.execute(
        select(GoogleCredentials).where(GoogleCredentials.user_id == user_id)
    )
    creds = result.scalar_one_or_none()
    if not creds:
        raise RuntimeError(f"No Google credentials found for user {user_id}")

    access_token = await refresh_access_token(google_refresh_token(creds))

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
        return resp.json().get("id")


async def send_email_in_background(
    user_id: UUID,
    email_id: UUID,
    subject: str,
    body: str,
) -> None:
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Email, Lead).join(Lead, Lead.id == Email.lead_id).where(Email.id == email_id)
            )
            row = result.one_or_none()
            email, lead = row if row else (None, None)
            if not lead or not lead.email:
                logger.warning("Email %s has no reachable lead", email_id)
                return

            provider_message_id = await send_email_on_behalf_of_user(
                db, user_id, lead.email, subject, body,
            )
            if provider_message_id:
                email.ai_metadata = {**(email.ai_metadata or {}), "provider_message_id": provider_message_id}
                await db.commit()
            logger.info(f"Gmail sent to {lead.email} for user {user_id}")
    except Exception as e:
        logger.error(f"Background Gmail send failed for user {user_id}: {e}")
