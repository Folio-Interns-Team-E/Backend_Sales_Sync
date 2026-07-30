from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_prop_18_proposal_revision_route_exists(client, api_user):
    user = await api_user("proposal-contract")
    team = await client.post("/teams/", json={"name": "Proposal Team"}, headers=user["headers"])
    team_id = team.json()["data"]["id"]
    response = await client.post(
        "/proposals/00000000-0000-0000-0000-000000000001/revisions",
        json={"title": "Revision", "summary": "Summary"},
        headers={**user["headers"], "X-Team-Id": team_id},
    )
    assert response.status_code != 404


@pytest.mark.asyncio
async def test_prop_13_static_template_route_is_not_captured_as_uuid(client, api_user):
    user = await api_user("template-contract")
    team = await client.post("/teams/", json={"name": "Template Team"}, headers=user["headers"])
    team_id = team.json()["data"]["id"]
    response = await client.get(
        "/proposals/template",
        headers={**user["headers"], "X-Team-Id": team_id},
    )
    assert not (
        response.status_code == 422
        and "uuid" in response.text.lower()
        and "proposal_id" in response.text
    )


@pytest.mark.asyncio
async def test_meet_04_frontend_meeting_payload_matches_backend(client, api_user):
    user = await api_user("meeting-contract")
    team = await client.post("/teams/", json={"name": "Meeting Team"}, headers=user["headers"])
    team_id = team.json()["data"]["id"]
    response = await client.post(
        "/meetings/",
        json={
            "client": "Test Client",
            "company": "Example",
            "date": "2026-08-01",
            "time": "10:00",
            "duration": "30 minutes",
            "agenda": ["Introduction", "Demo"],
        },
        headers={**user["headers"], "X-Team-Id": team_id},
    )
    assert response.status_code != 422
