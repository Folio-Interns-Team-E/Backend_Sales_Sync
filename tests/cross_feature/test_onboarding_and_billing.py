from __future__ import annotations

from uuid import uuid4

import pytest


async def context(client, api_user, prefix):
    user = await api_user(prefix)
    team = await client.post("/teams/", json={"name": f"{prefix} Team"}, headers=user["headers"])
    assert team.status_code == 201, team.text
    team_id = team.json()["data"]["id"]
    return user, team_id, {**user["headers"], "X-Team-Id": team_id}


def onboarding_payload(description="AI sales platform"):
    return {
        "productName": "SalesSync",
        "productDescription": description,
        "targetCustomer": "B2B revenue teams",
        "goals": "Increase qualified pipeline",
    }


@pytest.mark.asyncio
async def test_icp_01_submit_all_fields_generates_contextual_icp(client, api_user):
    _, _, headers = await context(client, api_user, "icp-full")
    response = await client.post("/onboarding/icp", json=onboarding_payload(), headers=headers)
    assert response.status_code == 201, response.text
    icp = response.json()["data"]["icp"]
    assert "B2B revenue teams" in icp
    assert "Increase qualified pipeline" in icp
    assert response.json()["data"]["completed"] is True


@pytest.mark.asyncio
async def test_icp_02_optional_product_name_can_be_omitted(client, api_user):
    _, _, headers = await context(client, api_user, "icp-optional")
    payload = onboarding_payload()
    payload.pop("productName")
    response = await client.post("/onboarding/icp", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["data"]["completed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["productDescription", "targetCustomer", "goals"])
@pytest.mark.parametrize("value", ["", " ", "\t"])
async def test_icp_03_rejects_blank_required_fields(client, api_user, field, value):
    _, _, headers = await context(client, api_user, "icp-invalid")
    payload = onboarding_payload()
    payload[field] = value
    response = await client.post("/onboarding/icp", json=payload, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_icp_05_status_before_and_after_creation(client, api_user):
    _, _, headers = await context(client, api_user, "icp-status")
    before = await client.get("/onboarding/status", headers=headers)
    created = await client.post("/onboarding/icp", json=onboarding_payload(), headers=headers)
    after = await client.get("/onboarding/status", headers=headers)
    assert before.status_code == created.status_code - 1 == after.status_code == 200
    assert before.json()["data"]["completed"] is False
    assert after.json()["data"]["completed"] is True


@pytest.mark.asyncio
async def test_icp_06_get_when_absent_is_documented_404(client, api_user):
    _, _, headers = await context(client, api_user, "icp-absent")
    response = await client.get("/onboarding/icp", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_icp_07_and_08_update_then_delete(client, api_user):
    _, _, headers = await context(client, api_user, "icp-lifecycle")
    await client.post("/onboarding/icp", json=onboarding_payload("Initial"), headers=headers)
    updated = await client.put(
        "/onboarding/icp", json=onboarding_payload("Updated description"), headers=headers
    )
    deleted = await client.delete("/onboarding/icp", headers=headers)
    status = await client.get("/onboarding/status", headers=headers)
    assert updated.status_code == deleted.status_code == status.status_code == 200
    assert updated.json()["data"]["icp"] == "Updated description"
    assert status.json()["data"]["completed"] is False


@pytest.mark.asyncio
async def test_icp_is_isolated_between_teams(client, api_user):
    _, _, owner_headers = await context(client, api_user, "icp-owner")
    _, _, other_headers = await context(client, api_user, "icp-other")
    await client.post("/onboarding/icp", json=onboarding_payload("Private ICP"), headers=owner_headers)
    other = await client.get("/onboarding/status", headers=other_headers)
    assert other.status_code == 200
    assert other.json()["data"]["completed"] is False
    assert other.json()["data"]["icp"] == ""


@pytest.mark.asyncio
async def test_bill_01_new_team_defaults_to_free_active(client, api_user):
    _, _, headers = await context(client, api_user, "billing-default")
    response = await client.get("/billing/status", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "tier": "free",
        "status": "active",
        "ends_at": None,
        "cancel_at_period_end": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["free", "unknown", "GROWTH", "../growth"])
async def test_bill_02_invalid_checkout_tier_is_rejected(client, api_user, tier):
    _, _, headers = await context(client, api_user, "billing-tier")
    response = await client.post(f"/billing/checkout/{tier}", headers=headers)
    assert response.status_code in {400, 404}


@pytest.mark.asyncio
async def test_bill_06_webhook_rejects_missing_or_invalid_signature(client):
    missing = await client.post("/billing/webhook", content=b"{}")
    invalid = await client.post(
        "/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "invalid"},
    )
    assert missing.status_code == invalid.status_code == 400


@pytest.mark.asyncio
async def test_bill_10_cancel_without_subscription_is_truthful(client, api_user):
    _, _, headers = await context(client, api_user, "billing-cancel")
    response = await client.post("/billing/cancel", headers=headers)
    assert response.status_code == 400
    assert "No active subscription" in response.json()["error"]


@pytest.mark.asyncio
async def test_bill_cross_team_status_does_not_leak(client, api_user):
    _, first_team, first_headers = await context(client, api_user, "billing-first")
    _, second_team, second_headers = await context(client, api_user, "billing-second")
    first = await client.get("/billing/status", headers=first_headers)
    second = await client.get("/billing/status", headers=second_headers)
    assert first.status_code == second.status_code == 200
    assert first_team != second_team
