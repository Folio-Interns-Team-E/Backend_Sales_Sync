from __future__ import annotations

from datetime import date, time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.main import app, unhandled_exception_handler
from tests.test_core_resources import create_lead, team_context
from tests.test_teams import create_team


async def create_meeting(client, headers, prefix="Remaining"):
    lead = await create_lead(client, headers, prefix)
    response = await client.post(
        "/meetings/",
        json={
            "lead_id": lead["id"],
            "date": "2027-02-20",
            "time": "11:30:00",
            "timezone": "UTC",
            "agenda": "Regression",
            "notes": "Initial",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return lead, response.json()["data"]


async def create_proposal(client, headers, lead_id=None, suffix="remaining"):
    payload = {
        "file_url": f"https://example.invalid/{suffix}.pdf",
        "file_type": "pdf",
        "file_size": 100,
    }
    if lead_id:
        payload["lead_id"] = lead_id
    response = await client.post("/proposals/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_core_01_health_is_safe_and_meaningful(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    assert "database_url" not in response.text.lower()
    assert "postgres:" not in response.text.lower()


@pytest.mark.asyncio
async def test_core_04_production_exception_does_not_leak_secret():
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = await unhandled_exception_handler(
        request, RuntimeError("password=super-secret postgresql://private")
    )
    body = response.body.decode()
    assert response.status_code == 500
    assert "super-secret" not in body
    assert "postgresql://" not in body


@pytest.mark.asyncio
async def test_team_09_admin_can_rename_team(client, api_user):
    admin = await api_user("rename-admin")
    team = await create_team(client, admin, "Before")
    response = await client.patch(
        f"/teams/{team['id']}",
        json={"name": "After"},
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "After"


@pytest.mark.asyncio
async def test_team_10_admin_delete_removes_team_access(client, api_user):
    admin = await api_user("delete-admin")
    team = await create_team(client, admin, "Delete Me")
    headers = {**admin["headers"], "X-Team-Id": team["id"]}
    deleted = await client.delete(f"/teams/{team['id']}", headers=headers)
    fetched = await client.get(f"/teams/{team['id']}", headers=headers)
    assert deleted.status_code == 200
    assert fetched.status_code in {403, 404}


@pytest.mark.asyncio
async def test_team_11_non_admin_cannot_delete_team(client, api_user):
    admin = await api_user("delete-owner")
    rep = await api_user("delete-rep")
    team = await create_team(client, admin)
    await client.post(
        "/teams/join", json={"invite_code": team["invite_code"]}, headers=rep["headers"]
    )
    response = await client.delete(
        f"/teams/{team['id']}",
        headers={**rep["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_team_20_invite_code_is_role_scoped(client, api_user):
    admin = await api_user("code-admin")
    rep = await api_user("code-rep")
    outsider = await api_user("code-outsider")
    team = await create_team(client, admin)
    await client.post(
        "/teams/join", json={"invite_code": team["invite_code"]}, headers=rep["headers"]
    )
    admin_response = await client.get(
        f"/teams/{team['id']}/invite-code",
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    rep_response = await client.get(
        f"/teams/{team['id']}/invite-code",
        headers={**rep["headers"], "X-Team-Id": team["id"]},
    )
    outsider_response = await client.get(
        f"/teams/{team['id']}/invite-code",
        headers={**outsider["headers"], "X-Team-Id": team["id"]},
    )
    assert admin_response.status_code == 200
    assert rep_response.status_code in {200, 403}
    assert outsider_response.status_code == 403


@pytest.mark.asyncio
async def test_lead_13_repeat_transitions_are_controlled(client, api_user):
    _, headers = await team_context(client, api_user, "repeat-transition")
    lead = await create_lead(client, headers, "Repeat")
    responses = [
        await client.post(f"/leads/{lead['id']}/qualify", headers=headers),
        await client.post(f"/leads/{lead['id']}/qualify", headers=headers),
        await client.post(f"/leads/{lead['id']}/discard", headers=headers),
        await client.post(f"/leads/{lead['id']}/discard", headers=headers),
    ]
    assert all(response.status_code in {200, 400, 409, 422} for response in responses)
    assert responses[-1].status_code != 500


@pytest.mark.asyncio
async def test_meet_05_06_07_list_get_patch_delete(client, api_user):
    _, headers = await team_context(client, api_user, "meeting-crud")
    _, meeting = await create_meeting(client, headers)
    listed = await client.get("/meetings/", headers=headers)
    fetched = await client.get(f"/meetings/{meeting['id']}", headers=headers)
    updated = await client.patch(
        f"/meetings/{meeting['id']}", json={"notes": "Changed"}, headers=headers
    )
    deleted = await client.delete(f"/meetings/{meeting['id']}", headers=headers)
    missing = await client.get(f"/meetings/{meeting['id']}", headers=headers)
    assert listed.status_code == fetched.status_code == updated.status_code == 200
    assert meeting["id"] in {item["id"] for item in listed.json()["data"]}
    assert updated.json()["data"]["notes"] == "Changed"
    assert deleted.status_code == 200
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_meet_09_cross_team_crud_is_denied(client, api_user):
    _, owner_headers = await team_context(client, api_user, "meeting-private")
    _, stranger_headers = await team_context(client, api_user, "meeting-stranger")
    _, meeting = await create_meeting(client, owner_headers, "PrivateMeeting")
    responses = [
        await client.get(f"/meetings/{meeting['id']}", headers=stranger_headers),
        await client.patch(
            f"/meetings/{meeting['id']}", json={"notes": "Stolen"}, headers=stranger_headers
        ),
        await client.delete(f"/meetings/{meeting['id']}", headers=stranger_headers),
    ]
    assert all(response.status_code in {403, 404} for response in responses)


@pytest.mark.asyncio
async def test_prop_04_05_06_list_get_and_patch(client, api_user):
    _, headers = await team_context(client, api_user, "proposal-crud")
    lead = await create_lead(client, headers, "ProposalCrud")
    proposal = await create_proposal(client, headers, lead["id"], "crud")
    listed = await client.get("/proposals/", headers=headers)
    fetched = await client.get(f"/proposals/{proposal['id']}", headers=headers)
    updated = await client.patch(
        f"/proposals/{proposal['id']}",
        json={"file_url": "https://example.invalid/changed.pdf"},
        headers=headers,
    )
    assert listed.status_code == fetched.status_code == updated.status_code == 200
    assert proposal["id"] in {item["id"] for item in listed.json()["data"]}
    assert updated.json()["data"]["file_url"].endswith("changed.pdf")


@pytest.mark.asyncio
async def test_prop_10_outcome_timestamp_is_idempotent(client, api_user):
    _, headers = await team_context(client, api_user, "proposal-idempotent")
    proposal = await create_proposal(client, headers)
    first = await client.patch(
        f"/proposals/{proposal['id']}/outcome", json={"outcome": "Won"}, headers=headers
    )
    second = await client.patch(
        f"/proposals/{proposal['id']}/outcome", json={"outcome": "Won"}, headers=headers
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["closed_at"] == second.json()["data"]["closed_at"]


@pytest.mark.asyncio
async def test_prop_14_template_absence_is_controlled(client, api_user):
    _, headers = await team_context(client, api_user, "template-absent")
    response = await client.get("/proposals/template", headers=headers)
    assert response.status_code in {200, 404}
    assert response.status_code != 500
