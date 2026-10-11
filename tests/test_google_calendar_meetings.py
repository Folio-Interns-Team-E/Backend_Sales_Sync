from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.google_calendar_service import create_calendar_meeting
from app.services.meetings_service import MeetingService


@pytest.mark.asyncio
async def test_google_event_requests_unique_meet_link_and_stores_no_attendee_invite():
    user_id = uuid4()
    credentials = SimpleNamespace(encrypted_refresh_token="encrypted")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: credentials)))
    response = SimpleNamespace(status_code=200, json=lambda: {"id": "google-event-1", "hangoutLink": "https://meet.google.com/abc-defg-hij"})
    client = MagicMock()
    client.get = AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: {"items": []}))
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    start = datetime.now(timezone.utc) + timedelta(days=1)

    with patch("app.services.google_calendar_service._calendar_access_token", new=AsyncMock(return_value="access")), patch("app.services.google_calendar_service.httpx.AsyncClient", return_value=client):
        created = await create_calendar_meeting(
            db, user_id, title="Meeting with Ada", description="Agenda", meeting_date=start.date(),
            meeting_time=start.time().replace(tzinfo=None), timezone_name="UTC", duration_minutes=30,
        )

    assert created == {"event_id": "google-event-1", "meet_url": "https://meet.google.com/abc-defg-hij"}
    payload = client.post.call_args.kwargs["json"]
    assert payload["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
    assert "attendees" not in payload  # Sharing the link must not silently email the prospect.
    assert client.post.call_args.kwargs["params"] == {"conferenceDataVersion": 1}


@pytest.mark.asyncio
async def test_meeting_is_not_saved_if_calendar_creation_fails():
    team_id, user_id, lead_id = uuid4(), uuid4(), uuid4()
    lead = SimpleNamespace(id=lead_id, team_id=team_id, name="Ada", company_name="Acme")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: lead)), add=MagicMock(), commit=AsyncMock())
    service = MeetingService(db)
    with patch("app.services.meetings_service.create_calendar_meeting", new=AsyncMock(side_effect=HTTPException(502, "Google failed"))):
        with pytest.raises(HTTPException) as error:
            await service.create_meeting(team_id, user_id, lead_id, datetime.now().date(), datetime.now().time(), "UTC")
    assert error.value.status_code == 502
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_google_calendar_conflict_blocks_event_creation():
    credentials = SimpleNamespace(encrypted_refresh_token="encrypted")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: credentials)))
    client = MagicMock()
    client.get = AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: {"items": [{"status": "confirmed"}]}))
    client.post = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    start = datetime.now(timezone.utc) + timedelta(days=1)
    with patch("app.services.google_calendar_service._calendar_access_token", new=AsyncMock(return_value="access")), patch("app.services.google_calendar_service.httpx.AsyncClient", return_value=client):
        with pytest.raises(HTTPException) as error:
            await create_calendar_meeting(db, uuid4(), title="Meeting", description="", meeting_date=start.date(), meeting_time=start.time().replace(tzinfo=None), timezone_name="UTC", duration_minutes=30)
    assert error.value.status_code == 409
    client.post.assert_not_called()
