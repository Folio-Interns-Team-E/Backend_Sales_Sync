import logging
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_key, encrypt_key
from app.core.redis import get_redis
from app.config import settings
from app.models.calcom_credentials import CalComIntegration
from app.models.meeting import Meeting, MeetingStatus

logger = logging.getLogger(__name__)
CAL_BASE_URL = "https://api.cal.com/v2"
CAL_API_VERSION = "2026-02-25"
CAL_AUTHORIZE_URL = "https://app.cal.com/auth/oauth2/authorize"
CAL_TOKEN_URL = f"{CAL_BASE_URL}/auth/oauth2/token"


def cal_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "cal-api-version": CAL_API_VERSION}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def calcom_callback_url() -> str:
    return settings.oauth_public_base_url.rstrip("/") + "/integrations/calcom/callback"


def begin_calcom_oauth(user_id: UUID, team_id: UUID) -> tuple[str, str]:
    if not settings.cal_oauth_client_id or not settings.cal_oauth_client_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Cal.com OAuth is not configured")
    redis = get_redis()
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Integration service is unavailable")
    state = secrets.token_urlsafe(32)
    binding = secrets.token_urlsafe(32)
    record = {"binding": _digest(binding), "user_id": str(user_id), "team_id": str(team_id)}
    redis.set("calcom_oauth:" + _digest(state), json.dumps(record), ex=600, nx=True)
    params = {
        "client_id": settings.cal_oauth_client_id,
        "redirect_uri": calcom_callback_url(),
        "state": state,
        "scope": "EVENT_TYPE_READ BOOKING_READ BOOKING_WRITE",
    }
    return CAL_AUTHORIZE_URL + "?" + urlencode(params), binding


def consume_calcom_oauth(state: str, binding: str | None) -> dict:
    if not state or len(state) > 128 or not binding:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Cal.com authorization state")
    redis = get_redis()
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Integration service is unavailable")
    key = "calcom_oauth:" + _digest(state)
    raw = redis.get(key)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cal.com authorization expired")
    record = json.loads(raw)
    if not hmac.compare_digest(record["binding"], _digest(binding)) or not redis.getdel(key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Cal.com authorization state")
    return record


async def exchange_calcom_code(code: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(CAL_TOKEN_URL, json={
                "client_id": settings.cal_oauth_client_id,
                "client_secret": settings.cal_oauth_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": calcom_callback_url(),
            })
    except httpx.RequestError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not reach Cal.com") from exc
    if response.status_code >= 400:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cal.com rejected the authorization")
    tokens = response.json()
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cal.com did not return valid credentials")
    return tokens


async def save_calcom_oauth(db: AsyncSession, team_id: UUID, user_id: UUID, tokens: dict):
    integration = await get_calcom_integration(db, team_id)
    if not integration:
        integration = CalComIntegration(user_id=user_id, team_id=team_id)
        db.add(integration)
    integration.user_id = user_id
    integration.credential_type = "oauth"
    integration.encrypted_api_key = None
    integration.encrypted_access_token = encrypt_key(tokens["access_token"])
    integration.encrypted_refresh_token = encrypt_key(tokens["refresh_token"])
    integration.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, int(tokens.get("expires_in", 1800))))
    await db.commit()
    await db.refresh(integration)
    return integration


async def oauth_access_token(db: AsyncSession, integration: CalComIntegration) -> str:
    now = datetime.now(timezone.utc)
    if integration.token_expires_at and integration.token_expires_at > now + timedelta(seconds=60):
        return decrypt_key(integration.encrypted_access_token)
    refresh_token = decrypt_key(integration.encrypted_refresh_token)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(CAL_TOKEN_URL, json={
                "client_id": settings.cal_oauth_client_id,
                "client_secret": settings.cal_oauth_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            })
    except httpx.RequestError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not refresh Cal.com access") from exc
    if response.status_code >= 400:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reconnect Cal.com in Settings")
    tokens = response.json()
    integration.encrypted_access_token = encrypt_key(tokens["access_token"])
    if tokens.get("refresh_token"):
        integration.encrypted_refresh_token = encrypt_key(tokens["refresh_token"])
    integration.token_expires_at = now + timedelta(seconds=max(60, int(tokens.get("expires_in", 1800))))
    await db.commit()
    return tokens["access_token"]


async def get_calcom_integration(db: AsyncSession, team_id: UUID):
    return (await db.execute(select(CalComIntegration).where(CalComIntegration.team_id == team_id))).scalar_one_or_none()


async def verify_calcom_credentials(api_key: str, event_type_id: str) -> None:
    try:
        numeric_id = int(event_type_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cal.com event type ID must be numeric") from exc
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{CAL_BASE_URL}/event-types/{numeric_id}", headers=cal_headers(api_key))
    except httpx.RequestError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not reach Cal.com") from exc
    if response.status_code in {401, 403}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cal.com rejected this API key")
    if response.status_code == 404:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cal.com event type was not found")
    if response.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Cal.com could not verify the integration")


async def save_or_update_calcom(db: AsyncSession, team_id: UUID, user_id: UUID, api_key: str, event_type_id: str):
    api_key = api_key.strip()
    event_type_id = event_type_id.strip()
    await verify_calcom_credentials(api_key, event_type_id)
    integration = await get_calcom_integration(db, team_id)
    if integration:
        integration.user_id = user_id
        integration.encrypted_api_key = encrypt_key(api_key)
        integration.event_type_id = event_type_id
    else:
        integration = CalComIntegration(user_id=user_id, team_id=team_id, encrypted_api_key=encrypt_key(api_key), event_type_id=event_type_id)
        db.add(integration)
    integration.credential_type = "api_key"
    integration.encrypted_access_token = None
    integration.encrypted_refresh_token = None
    integration.token_expires_at = None
    await db.commit()
    await db.refresh(integration)
    return integration


class CalComService:
    def __init__(self, db: AsyncSession, team_id: UUID):
        self.db = db
        self.team_id = team_id

    async def _credentials(self) -> tuple[str, str]:
        integration = await get_calcom_integration(self.db, self.team_id)
        if not integration:
            raise HTTPException(status.HTTP_409_CONFLICT, "Connect Cal.com in Settings before scheduling meetings")
        if not integration.event_type_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Choose a Cal.com event type in Settings")
        if integration.credential_type == "oauth":
            return await oauth_access_token(self.db, integration), integration.event_type_id
        return decrypt_key(integration.encrypted_api_key), integration.event_type_id

    async def create_booking(self, *, lead_id, start_time: datetime, name: str, email: str, agenda=None):
        api_key, event_type_id = await self._credentials()
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=ZoneInfo("Asia/Karachi"))
        payload = {"start": start_time.isoformat(), "attendee": {"name": name, "timeZone": "Asia/Karachi", "language": "en", "email": email}, "eventTypeId": int(event_type_id)}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{CAL_BASE_URL}/bookings", headers=cal_headers(api_key), json=payload)
        if response.status_code not in {200, 201}:
            logger.warning("Cal.com booking failed with status %s", response.status_code)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Cal.com could not create the booking")
        booking = response.json().get("data", {})
        booking_uid = booking.get("uid") or booking.get("id")
        meeting = Meeting(lead_id=lead_id, date=start_time.date(), time=start_time.time(), timezone="Asia/Karachi", calendar_event_id=str(booking_uid), agenda=agenda, status=MeetingStatus.SCHEDULED.value)
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)
        return {"meeting_id": meeting.id, "cal_booking_uid": booking_uid, "status": "scheduled"}

    async def cancel_booking(self, booking_uid: str, meeting_id):
        api_key, _ = await self._credentials()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{CAL_BASE_URL}/bookings/{booking_uid}/cancel", headers=cal_headers(api_key), json={"cancellationReason": "User requested cancellation"})
        if response.status_code not in {200, 204}:
            logger.warning("Cal.com cancellation failed with status %s", response.status_code)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Cal.com could not cancel the booking")
        meeting = (await self.db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalar_one_or_none()
        if meeting:
            meeting.status = MeetingStatus.CANCELLED.value
            await self.db.commit()
        return {"status": "cancelled", "booking_uid": booking_uid}
