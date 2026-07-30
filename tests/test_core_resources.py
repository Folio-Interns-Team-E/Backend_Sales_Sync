from __future__ import annotations

from uuid import uuid4

import pytest


async def team_context(client, api_user, prefix: str):
    user = await api_user(prefix)
    response = await client.post(
        "/teams/", json={"name": f"{prefix} Team"}, headers=user["headers"]
    )
    assert response.status_code == 201, response.text
    team_id = response.json()["data"]["id"]
    return user, {**user["headers"], "X-Team-Id": team_id}


async def create_lead(client, headers, prefix: str = "Lead"):
    response = await client.post(
        "/leads/",
        json={
            "name": f"{prefix} Person",
            "email": f"{prefix.lower()}-{uuid4().hex}@example.com",
            "company": "Example Co",
            "title": "Buyer",
            "source": "Referral",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_lead_01_create_full_and_minimum_leads(client, api_user):
    _, headers = await team_context(client, api_user, "lead-create")
    full = await create_lead(client, headers, "Full")
    minimum = await client.post(
        "/leads/",
        json={"name": "Minimum", "email": f"minimum-{uuid4().hex}@example.com"},
        headers=headers,
    )
    assert minimum.status_code == 201, minimum.text
    assert full["status"] == minimum.json()["data"]["status"] == "New"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", " ", "\t"])
async def test_lead_02_rejects_blank_names(client, api_user, name):
    _, headers = await team_context(client, api_user, "lead-blank")
    response = await client.post(
        "/leads/",
        json={"name": name, "email": f"blank-{uuid4().hex}@example.com"},
        headers=headers,
    )
    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_lead_02_rejects_invalid_email(client, api_user):
    _, headers = await team_context(client, api_user, "lead-email")
    response = await client.post(
        "/leads/", json={"name": "Invalid Email", "email": "not-an-email"}, headers=headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_lead_03_duplicate_email_rule_is_enforced_per_team(client, api_user):
    _, headers = await team_context(client, api_user, "lead-duplicate")
    email = f"duplicate-{uuid4().hex}@example.com"
    first = await client.post("/leads/", json={"name": "One", "email": email}, headers=headers)
    second = await client.post("/leads/", json={"name": "Two", "email": email}, headers=headers)
    assert first.status_code == 201
    assert second.status_code in {400, 409, 422}


@pytest.mark.asyncio
async def test_lead_04_list_get_and_filter(client, api_user):
    _, headers = await team_context(client, api_user, "lead-list")
    lead = await create_lead(client, headers, "Listed")
    listed = await client.get("/leads/?status=New", headers=headers)
    fetched = await client.get(f"/leads/{lead['id']}", headers=headers)
    assert listed.status_code == fetched.status_code == 200
    assert lead["id"] in {item["id"] for item in listed.json()["data"]}
    assert fetched.json()["data"]["id"] == lead["id"]


@pytest.mark.asyncio
async def test_lead_05_invalid_status_filter_is_controlled(client, api_user):
    _, headers = await team_context(client, api_user, "lead-filter")
    response = await client.get("/leads/?status=not-a-status", headers=headers)
    assert response.status_code in {200, 400, 422}


@pytest.mark.asyncio
async def test_lead_09_patch_preserves_omitted_fields(client, api_user):
    _, headers = await team_context(client, api_user, "lead-patch")
    lead = await create_lead(client, headers, "Before")
    response = await client.patch(
        f"/leads/{lead['id']}", json={"company": "Changed Co"}, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["company"] == "Changed Co"
    assert data["name"] == lead["name"]
    assert data["email"] == lead["email"]


@pytest.mark.asyncio
async def test_lead_10_status_score_reasoning_are_persisted(client, api_user):
    _, headers = await team_context(client, api_user, "lead-enrichment")
    lead = await create_lead(client, headers, "Enriched")
    response = await client.patch(
        f"/leads/{lead['id']}/status",
        json={"status": "Analyzed", "score": 88, "reasoning": "Strong fit"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["status"], data["score"], data["reasoning"]) == (
        "Analyzed",
        88,
        "Strong fit",
    )


@pytest.mark.asyncio
async def test_lead_11_and_12_qualify_then_discard(client, api_user):
    _, headers = await team_context(client, api_user, "lead-transition")
    lead = await create_lead(client, headers, "Transition")
    qualified = await client.post(f"/leads/{lead['id']}/qualify", headers=headers)
    discarded = await client.post(f"/leads/{lead['id']}/discard", headers=headers)
    assert qualified.status_code == discarded.status_code == 200
    assert qualified.json()["data"]["status"] == "Qualified"
    assert discarded.json()["data"]["status"] == "Discarded"


@pytest.mark.asyncio
async def test_lead_16_cross_team_crud_is_denied(client, api_user):
    _, owner_headers = await team_context(client, api_user, "lead-owner")
    _, stranger_headers = await team_context(client, api_user, "lead-stranger")
    lead = await create_lead(client, owner_headers, "Private")
    requests = [
        await client.get(f"/leads/{lead['id']}", headers=stranger_headers),
        await client.patch(f"/leads/{lead['id']}", json={"name": "Stolen"}, headers=stranger_headers),
        await client.post(f"/leads/{lead['id']}/qualify", headers=stranger_headers),
        await client.post(f"/leads/{lead['id']}/discard", headers=stranger_headers),
        await client.delete(f"/leads/{lead['id']}", headers=stranger_headers),
    ]
    assert all(response.status_code in {403, 404} for response in requests)


@pytest.mark.asyncio
async def test_lead_17_frontend_create_enrichment_is_not_silently_lost(client, api_user):
    _, headers = await team_context(client, api_user, "lead-contract")
    response = await client.post(
        "/leads/",
        json={
            "name": "Frontend Lead",
            "email": f"frontend-{uuid4().hex}@example.com",
            "status": "Analyzed",
            "score": 75,
            "reasoning": "Contract value",
        },
        headers=headers,
    )
    assert response.status_code in {400, 422} or (
        response.json()["data"]["status"] == "Analyzed"
        and response.json()["data"]["score"] == 75
        and response.json()["data"]["reasoning"] == "Contract value"
    )


@pytest.mark.asyncio
async def test_meet_01_create_valid_meeting(client, api_user):
    _, headers = await team_context(client, api_user, "meeting-create")
    lead = await create_lead(client, headers, "Meeting")
    response = await client.post(
        "/meetings/",
        json={
            "lead_id": lead["id"],
            "date": "2027-01-15",
            "time": "10:30:00",
            "timezone": "UTC",
            "agenda": "Discovery",
            "notes": "Prepared",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "Scheduled"


@pytest.mark.asyncio
async def test_meet_02_missing_nonexistent_and_cross_team_leads(client, api_user):
    _, headers = await team_context(client, api_user, "meeting-invalid")
    _, other_headers = await team_context(client, api_user, "meeting-other")
    other_lead = await create_lead(client, other_headers, "Other")
    common = {"date": "2027-01-15", "time": "10:30:00", "timezone": "UTC"}
    missing = await client.post("/meetings/", json=common, headers=headers)
    nonexistent = await client.post(
        "/meetings/", json={**common, "lead_id": str(uuid4())}, headers=headers
    )
    cross_team = await client.post(
        "/meetings/", json={**common, "lead_id": other_lead["id"]}, headers=headers
    )
    assert missing.status_code == 422
    assert nonexistent.status_code in {403, 404}
    assert cross_team.status_code in {403, 404}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [("date", "not-a-date"), ("time", "25:00"), ("timezone", "")],
)
async def test_meet_03_rejects_invalid_schedule_values(client, api_user, field, value):
    _, headers = await team_context(client, api_user, "meeting-validation")
    lead = await create_lead(client, headers, "Schedule")
    payload = {
        "lead_id": lead["id"],
        "date": "2027-01-15",
        "time": "10:30:00",
        "timezone": "UTC",
        field: value,
    }
    response = await client.post("/meetings/", json=payload, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_prop_01_create_valid_proposal(client, api_user):
    _, headers = await team_context(client, api_user, "proposal-create")
    lead = await create_lead(client, headers, "Proposal")
    response = await client.post(
        "/proposals/",
        json={
            "file_url": "https://example.invalid/proposal.pdf",
            "lead_id": lead["id"],
            "file_type": "pdf",
            "file_size": 1024,
            "ai_metadata": {"source": "test"},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert (data["status"], data["outcome"], data["version"]) == ("Draft", "Open", 1)


@pytest.mark.asyncio
async def test_prop_02_rejects_missing_url_and_negative_size(client, api_user):
    _, headers = await team_context(client, api_user, "proposal-invalid")
    missing = await client.post("/proposals/", json={}, headers=headers)
    negative = await client.post(
        "/proposals/",
        json={"file_url": "https://example.invalid/file.pdf", "file_size": -1},
        headers=headers,
    )
    assert missing.status_code == 422
    assert negative.status_code == 422


@pytest.mark.asyncio
async def test_prop_03_frontend_create_contract_is_not_silently_lost(client, api_user):
    _, headers = await team_context(client, api_user, "proposal-contract")
    response = await client.post(
        "/proposals/",
        json={"company": "Acme", "title": "Deal", "summary": "Summary", "value": 1000},
        headers=headers,
    )
    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_prop_07_valid_and_invalid_statuses(client, api_user):
    _, headers = await team_context(client, api_user, "proposal-status")
    created = await client.post(
        "/proposals/",
        json={"file_url": "https://example.invalid/status.pdf"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    proposal_id = created.json()["data"]["id"]
    for status in ["Draft", "Sent", "Under Review", "Accepted", "Rejected"]:
        response = await client.patch(
            f"/proposals/{proposal_id}/status", json={"status": status}, headers=headers
        )
        assert response.status_code == 200, response.text
    invalid = await client.patch(
        f"/proposals/{proposal_id}/status", json={"status": "accepted"}, headers=headers
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_prop_09_valid_and_invalid_outcomes(client, api_user):
    _, headers = await team_context(client, api_user, "proposal-outcome")
    created = await client.post(
        "/proposals/",
        json={"file_url": "https://example.invalid/outcome.pdf"},
        headers=headers,
    )
    proposal_id = created.json()["data"]["id"]
    won = await client.patch(
        f"/proposals/{proposal_id}/outcome", json={"outcome": "Won"}, headers=headers
    )
    assert won.status_code == 200
    assert won.json()["data"]["status"] == "Accepted"
    invalid = await client.patch(
        f"/proposals/{proposal_id}/outcome", json={"outcome": "won"}, headers=headers
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_prop_12_cross_team_proposal_is_denied(client, api_user):
    _, owner_headers = await team_context(client, api_user, "proposal-owner")
    _, stranger_headers = await team_context(client, api_user, "proposal-stranger")
    lead = await create_lead(client, owner_headers, "Owned")
    created = await client.post(
        "/proposals/",
        json={"file_url": "https://example.invalid/private.pdf", "lead_id": lead["id"]},
        headers=owner_headers,
    )
    proposal_id = created.json()["data"]["id"]
    requests = [
        await client.get(f"/proposals/{proposal_id}", headers=stranger_headers),
        await client.patch(
            f"/proposals/{proposal_id}",
            json={"file_url": "https://example.invalid/stolen.pdf"},
            headers=stranger_headers,
        ),
        await client.patch(
            f"/proposals/{proposal_id}/status",
            json={"status": "Sent"},
            headers=stranger_headers,
        ),
        await client.delete(f"/proposals/{proposal_id}", headers=stranger_headers),
    ]
    assert all(response.status_code in {403, 404} for response in requests)
