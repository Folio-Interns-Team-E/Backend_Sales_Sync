from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.google_calendar_service import create_calendar_meeting
from app.services.meetings_service import MeetingService
from app.ai.meeting_agent import MeetingAgent


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


@pytest.mark.asyncio
async def test_ai_meeting_request_is_prepared_without_being_executed():
    team_id, lead_id = uuid4(), uuid4()
    lead = SimpleNamespace(
        id=lead_id,
        team_id=team_id,
        name="Ada Lovelace",
        company_name="Analytical Engines",
        email="ada@example.com",
    )
    rows = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [lead]))
    db = SimpleNamespace(execute=AsyncMock(return_value=rows))
    agent = MeetingAgent(db)
    agent._compile_meeting_decision = AsyncMock(return_value={
        "decision": "CREATE",
        "matched_lead_id": str(lead_id),
        "start_time": "2026-10-21T14:00:00",
        "timezone": "Asia/Karachi",
        "target_cancel_time": None,
        "clarification_message": None,
    })
    agent._execute_create = AsyncMock()

    pending, message = await agent.prepare(
        "Schedule Ada tomorrow at 2 PM",
        team_id,
    )

    assert pending == {
        "type": "meeting",
        "decision": "CREATE",
        "lead_id": str(lead_id),
        "start_time": "2026-10-21T14:00:00",
        "timezone": "Asia/Karachi",
        "target_cancel_time": None,
    }
    assert "Please confirm" in message
    assert "Ada Lovelace" in message
    agent._execute_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_meeting_revalidates_workspace_before_execution():
    team_id, user_id, lead_id = uuid4(), uuid4(), uuid4()
    lead = SimpleNamespace(id=lead_id, team_id=team_id, name="Ada Lovelace")
    result = SimpleNamespace(scalar_one_or_none=lambda: lead)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    agent = MeetingAgent(db)
    agent._execute_create = AsyncMock(return_value="scheduled")
    pending = {
        "type": "meeting",
        "decision": "CREATE",
        "lead_id": str(lead_id),
        "start_time": "2026-10-21T14:00:00",
        "timezone": "Asia/Karachi",
    }

    response = await agent.execute_prepared(pending, team_id, user_id)

    assert response == "scheduled"
    agent._execute_create.assert_awaited_once_with(
        lead,
        "2026-10-21T14:00:00",
        user_id,
        "Asia/Karachi",
    )


@pytest.mark.asyncio
async def test_created_meeting_exposes_structured_chat_action():
    team_id, user_id, lead_id, meeting_id = uuid4(), uuid4(), uuid4(), uuid4()
    lead = SimpleNamespace(
        id=lead_id,
        team_id=team_id,
        name="Ada Lovelace",
        email="ada@example.com",
    )
    meeting = SimpleNamespace(
        id=meeting_id,
        meet_url="https://meet.google.com/abc-defg-hij",
    )
    db = SimpleNamespace()
    agent = MeetingAgent(db)

    with patch(
        "app.ai.meeting_agent.MeetingService.create_meeting",
        new=AsyncMock(return_value=meeting),
    ):
        response = await agent._execute_create(
            lead,
            "2026-10-21T14:00:00",
            user_id,
            "Asia/Karachi",
        )

    assert "Meeting Scheduled Successfully" in response
    assert agent.action_result == {
        "type": "meeting_created",
        "meeting_id": str(meeting_id),
        "meet_url": "https://meet.google.com/abc-defg-hij",
    }
