from __future__ import annotations

from datetime import date, time, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import SessionLocal
from app.main import app
from app.models.meeting import Meeting
from tests.test_core_resources import create_lead, team_context


async def _meeting_context(client, api_user, prefix: str):
    user, headers = await team_context(client, api_user, prefix)
    lead = await create_lead(client, headers, prefix)
    async with SessionLocal() as db:
        meeting = Meeting(
            lead_id=UUID(lead["id"]),
            created_by=UUID(user["id"]),
            date=date.today() + timedelta(days=14),
            time=time(10, 30),
            timezone="UTC",
            agenda="Discovery",
            notes="Initial notes",
            calendar_event_id="calendar-initial",
            status="Scheduled",
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        meeting_id = str(meeting.id)
    return user, headers, lead, meeting_id


@pytest.mark.asyncio
async def test_meet_06_patch_all_fields_then_partial_patch_preserves_omitted_values(
    client, api_user
):
    _, headers, _, meeting_id = await _meeting_context(client, api_user, "meet-update")
    updated = await client.patch(
        f"/meetings/{meeting_id}",
        json={
            "date": "2031-05-20",
            "time": "15:45:00",
            "timezone": "Asia/Karachi",
            "agenda": "Demo and commercial review",
            "notes": "Bring implementation team",
            "calendar_event_id": "calendar-replaced",
        },
        headers=headers,
    )
    partial = await client.patch(
        f"/meetings/{meeting_id}",
        json={"notes": "Only notes changed"},
        headers=headers,
    )

    assert updated.status_code == 200, updated.text
    assert partial.status_code == 200, partial.text
    data = partial.json()["data"]
    assert data["date"] == "2031-05-20"
    assert data["time"] == "15:45:00"
    assert data["timezone"] == "Asia/Karachi"
    assert data["agenda"] == "Demo and commercial review"
    assert data["notes"] == "Only notes changed"
    assert data["calendar_event_id"] == "calendar-replaced"


@pytest.mark.asyncio
async def test_meet_07_valid_forward_lifecycle_and_backward_transition_rules(
    client, api_user
):
    _, headers, _, meeting_id = await _meeting_context(client, api_user, "meet-lifecycle")
    live = await client.patch(
        f"/meetings/{meeting_id}", json={"status": "Live"}, headers=headers
    )
    completed = await client.patch(
        f"/meetings/{meeting_id}", json={"status": "Completed"}, headers=headers
    )
    backwards = await client.patch(
        f"/meetings/{meeting_id}", json={"status": "Live"}, headers=headers
    )

    assert live.status_code == completed.status_code == 200
    assert live.json()["data"]["status"] == "Live"
    assert completed.json()["data"]["status"] == "Completed"
    assert backwards.status_code in {400, 409, 422}
    fetched = await client.get(f"/meetings/{meeting_id}", headers=headers)
    assert fetched.json()["data"]["status"] == "Completed"


@pytest.mark.asyncio
async def test_meet_07_invalid_status_is_controlled_and_does_not_mutate(
    client, api_user
):
    _, headers, _, meeting_id = await _meeting_context(client, api_user, "meet-invalid")
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        invalid = await safe_client.patch(
            f"/meetings/{meeting_id}",
            json={"status": "Definitely-Not-A-Status"},
            headers=headers,
        )
    assert invalid.status_code in {400, 409, 422}
    fetched = await client.get(f"/meetings/{meeting_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["status"] == "Scheduled"


@pytest.mark.asyncio
async def test_meet_08_frontend_transcript_is_rejected_instead_of_silently_dropped(
    client, api_user
):
    _, headers, _, meeting_id = await _meeting_context(client, api_user, "meet-transcript")
    response = await client.patch(
        f"/meetings/{meeting_id}",
        json={"transcript": "Customer agreed to a pilot."},
        headers=headers,
    )
    assert response.status_code == 422
    assert "transcript" in response.text.lower()


@pytest.mark.asyncio
async def test_meet_10_cross_team_get_update_and_delete_are_denied(client, api_user):
    _, owner_headers, _, meeting_id = await _meeting_context(
        client, api_user, "meet-owner"
    )
    _, stranger_headers = await team_context(client, api_user, "meet-stranger")

    denied = [
        await client.get(f"/meetings/{meeting_id}", headers=stranger_headers),
        await client.patch(
            f"/meetings/{meeting_id}",
            json={"notes": "Cross-team overwrite"},
            headers=stranger_headers,
        ),
        await client.delete(f"/meetings/{meeting_id}", headers=stranger_headers),
    ]
    assert all(response.status_code in {403, 404} for response in denied)
    owner = await client.get(f"/meetings/{meeting_id}", headers=owner_headers)
    assert owner.status_code == 200
    assert owner.json()["data"]["notes"] == "Initial notes"
