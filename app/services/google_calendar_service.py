"""Per-user Google Calendar OAuth and Google Meet event creation."""

import hashlib
import asyncio
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import decrypt_key, encrypt_key
from app.core.redis import get_redis
from app.models.google_calendar_credentials import GoogleCalendarCredentials

logger = logging.getLogger(__name__)
TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def calendar_callback_url() -> str:
    return settings.oauth_public_base_url.rstrip("/") + "/integrations/google-calendar/callback"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def begin_calendar_oauth(user_id: UUID) -> tuple[str, str]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google Calendar OAuth is not configured")
    redis = get_redis()
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Integration state service is unavailable")
    state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    redis.set("calendar_oauth:" + _digest(state), json.dumps({"user_id": str(user_id), "binding": _digest(binding)}), ex=600, nx=True)
    return state, binding


def consume_calendar_oauth(state: str, binding: str | None) -> UUID:
    if not state or len(state) > 128 or not binding:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Google Calendar authorization state")
    redis = get_redis()
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Integration state service is unavailable")
    key = "calendar_oauth:" + _digest(state)
    raw = redis.get(key)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google Calendar authorization expired")
    record = json.loads(raw)
    if not hmac.compare_digest(record["binding"], _digest(binding)) or not redis.getdel(key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Google Calendar authorization state")
    return UUID(record["user_id"])


async def exchange_calendar_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": calendar_callback_url(),
            "grant_type": "authorization_code",
        })
        response.raise_for_status()
        return response.json()


async def calendar_email(access_token: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        return response.json()["email"]


async def save_calendar_credentials(db: AsyncSession, user_id: UUID, token_data: dict) -> GoogleCalendarCredentials:
    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")
    if not refresh_token or not access_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google did not grant offline Calendar access")
    email = await calendar_email(access_token)
    record = (await db.execute(select(GoogleCalendarCredentials).where(GoogleCalendarCredentials.user_id == user_id))).scalar_one_or_none()
    if record is None:
        record = GoogleCalendarCredentials(user_id=user_id)
        db.add(record)
    record.google_email = email
    record.encrypted_refresh_token = encrypt_key(refresh_token)
    await db.commit()
    return record


async def _calendar_access_token(credentials: GoogleCalendarCredentials) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(TOKEN_URL, data={
            "refresh_token": decrypt_key(credentials.encrypted_refresh_token),
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        })
        if response.status_code >= 400:
            logger.warning("Google Calendar token refresh failed: %s", response.status_code)
            raise HTTPException(status.HTTP_409_CONFLICT, "Reconnect Google Calendar in Settings")
        return response.json()["access_token"]


async def create_calendar_meeting(
    db: AsyncSession, user_id: UUID, *, title: str, description: str,
    meeting_date, meeting_time, timezone_name: str, duration_minutes: int,
) -> dict:
    record = (await db.execute(select(GoogleCalendarCredentials).where(GoogleCalendarCredentials.user_id == user_id))).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Google Calendar in Settings before creating meetings")
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid time zone") from exc
    start = datetime.combine(meeting_date, meeting_time, tzinfo=tz)
    if start.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Meeting time must be in the future")
    end = start + timedelta(minutes=duration_minutes)
    access_token = await _calendar_access_token(record)
    payload = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
        "conferenceData": {"createRequest": {"requestId": secrets.token_hex(16), "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        availability = await client.get(EVENTS_URL, headers=headers, params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(),
            "singleEvents": "true", "maxResults": 100,
        })
        if availability.status_code >= 400:
            logger.warning("Google Calendar availability check failed: %s", availability.status_code)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not verify Google Calendar availability")
        if any(item.get("status") != "cancelled" and item.get("transparency") != "transparent" for item in availability.json().get("items", [])):
            raise HTTPException(status.HTTP_409_CONFLICT, "Your Google Calendar is busy at that time")
        response = await client.post(EVENTS_URL, params={"conferenceDataVersion": 1}, headers=headers, json=payload)
        if response.status_code >= 400:
            logger.warning("Google Calendar event creation failed: %s", response.status_code)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google Calendar could not create the meeting")
        event = response.json()
        for _ in range(5):
            meet_url = event.get("hangoutLink") or next((item.get("uri") for item in event.get("conferenceData", {}).get("entryPoints", []) if item.get("entryPointType") == "video"), None)
            if meet_url:
                return {"event_id": event["id"], "meet_url": meet_url}
            await asyncio.sleep(1)
            check = await client.get(f"{EVENTS_URL}/{event['id']}", headers=headers)
            if check.status_code >= 400:
                break
            event = check.json()
        # Do not leave a calendar event without the promised meeting link.
        await client.delete(f"{EVENTS_URL}/{event['id']}", headers=headers)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google Meet link could not be generated; no meeting was saved")


async def delete_calendar_meeting(db: AsyncSession, user_id: UUID, event_id: str) -> None:
    record = (await db.execute(select(GoogleCalendarCredentials).where(GoogleCalendarCredentials.user_id == user_id))).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reconnect the meeting organizer's Google Calendar")
    access_token = await _calendar_access_token(record)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.delete(f"{EVENTS_URL}/{event_id}", headers={"Authorization": f"Bearer {access_token}"}, params={"sendUpdates": "all"})
    if response.status_code not in {204, 404, 410}:
        logger.warning("Google Calendar event cancellation failed: %s", response.status_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google Calendar could not cancel the meeting")
