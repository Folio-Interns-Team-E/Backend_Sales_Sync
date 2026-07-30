from __future__ import annotations

from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest

from tests.test_core_resources import create_lead, team_context
from tests.test_teams import create_team


@pytest.mark.asyncio
async def test_core_07_foreign_and_unknown_uuids_are_indistinguishable(
    client, api_user
):
    _, owner_headers = await team_context(client, api_user, "core-07-owner")
    lead = await create_lead(client, owner_headers, "Private")
    _, attacker_headers = await team_context(client, api_user, "core-07-attacker")
    unknown_id = str(uuid4())

    foreign_samples = []
    unknown_samples = []
    foreign_responses = []
    unknown_responses = []
    for _ in range(12):
        started = perf_counter()
        foreign = await client.get(f"/leads/{lead['id']}", headers=attacker_headers)
        foreign_samples.append(perf_counter() - started)
        foreign_responses.append(foreign)

        started = perf_counter()
        unknown = await client.get(f"/leads/{unknown_id}", headers=attacker_headers)
        unknown_samples.append(perf_counter() - started)
        unknown_responses.append(unknown)

    assert {response.status_code for response in foreign_responses} == {404}
    assert {response.status_code for response in unknown_responses} == {404}
    assert {response.text for response in foreign_responses} == {
        response.text for response in unknown_responses
    }
    assert lead["name"] not in foreign_responses[0].text
    timing_gap = abs(median(foreign_samples) - median(unknown_samples))
    assert timing_gap < max(0.05, median(unknown_samples) * 4)


@pytest.mark.asyncio
async def test_core_08_unknown_json_fields_follow_consistent_ignore_policy(
    client, api_user
):
    user = await api_user("core-08")
    created_team = await client.post(
        "/teams/",
        json={
            "name": "CORE-08 Team",
            "unknown": "must-not-persist",
            "admin": True,
            "subscription_tier": "enterprise",
        },
        headers=user["headers"],
    )
    assert created_team.status_code == 201, created_team.text
    team = created_team.json()["data"]
    assert set(team).isdisjoint({"unknown", "admin", "subscription_tier"})
    headers = {**user["headers"], "X-Team-Id": team["id"]}

    updated_team = await client.patch(
        f"/teams/{team['id']}",
        json={"name": "CORE-08 Updated", "role": "admin", "owner_id": str(uuid4())},
        headers=headers,
    )
    created_lead = await client.post(
        "/leads/",
        json={
            "name": "CORE-08 Lead",
            "email": f"core08-{uuid4().hex}@example.com",
            "unknown": {"nested": True},
            "score": 100,
            "status": "Converted",
            "team_id": str(uuid4()),
        },
        headers=headers,
    )
    assert updated_team.status_code == 200, updated_team.text
    assert created_lead.status_code == 201, created_lead.text
    assert set(updated_team.json()["data"]).isdisjoint({"role", "owner_id"})
    lead = created_lead.json()["data"]
    assert set(lead).isdisjoint({"unknown"})
    assert lead["score"] is None
    assert lead["status"] == "New"
    assert lead["team_id"] == team["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"", "application/json"),
        (b'{"name":', "application/json"),
        (b'{"name":"Text body"}', "text/plain"),
        (b'{"name":"First","name":"Second"}', "application/json"),
    ],
    ids=["empty", "malformed", "wrong-content-type", "duplicate-keys"],
)
async def test_core_09_invalid_json_forms_are_controlled_without_mutation(
    client, api_user, content, content_type
):
    user = await api_user("core-09")
    before = await client.get("/teams/", headers=user["headers"])
    assert before.status_code == 200 and before.json()["data"] == []

    response = await client.post(
        "/teams/",
        content=content,
        headers={**user["headers"], "Content-Type": content_type},
    )
    after = await client.get("/teams/", headers=user["headers"])

    assert response.status_code in {400, 415, 422}
    assert after.status_code == 200
    assert after.json()["data"] == []
    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()
        assert body["success"] is False
        assert body["data"] is None
