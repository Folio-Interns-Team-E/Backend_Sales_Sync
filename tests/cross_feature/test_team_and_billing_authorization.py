from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import billing_service, teams_service
from tests.teams.test_team_api import create_team


async def joined_team(client, api_user, prefix: str):
    admin = await api_user(f"{prefix}-admin")
    member = await api_user(f"{prefix}-member")
    team = await create_team(client, admin, f"{prefix} Team")
    joined = await client.post(
        "/teams/join",
        json={"invite_code": team["invite_code"]},
        headers=member["headers"],
    )
    assert joined.status_code == 200, joined.text
    return admin, member, team


@pytest.mark.asyncio
async def test_team_12_invite_contains_correct_team_code_link_and_recipient(
    client, api_user, monkeypatch
):
    admin = await api_user("invite-content")
    team = await create_team(client, admin, "Invite Content Team")
    captured = {}

    def fake_send(payload):
        captured.update(payload)
        return {"id": "test-only"}

    monkeypatch.setattr(teams_service.resend.Emails, "send", fake_send)
    recipient = f"invite-{uuid4().hex}@example.com"
    response = await client.post(
        "/teams/invite",
        json={"email": recipient},
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 200, response.text
    assert captured["to"] == [recipient]
    assert "Invite Content Team" in captured["html"]
    assert team["invite_code"] in captured["html"]
    assert f"/team-setup?invite={team['invite_code']}" in captured["html"]


@pytest.mark.asyncio
async def test_team_13_invalid_existing_and_teamless_invites_are_rejected_without_send(
    client, api_user, monkeypatch
):
    sends = 0

    def fake_send(payload):
        nonlocal sends
        sends += 1
        return {"id": "test-only"}

    monkeypatch.setattr(teams_service.resend.Emails, "send", fake_send)
    admin, member, team = await joined_team(client, api_user, "invite-validation")
    admin_headers = {**admin["headers"], "X-Team-Id": team["id"]}
    malformed = await client.post(
        "/teams/invite", json={"email": "not-an-email"}, headers=admin_headers
    )
    existing = await client.post(
        "/teams/invite", json={"email": member["email"]}, headers=admin_headers
    )
    teamless = await api_user("invite-teamless")
    no_team = await client.post(
        "/teams/invite",
        json={"email": f"new-{uuid4().hex}@example.com"},
        headers=teamless["headers"],
    )
    assert malformed.status_code == 422
    assert existing.status_code in {400, 409}
    assert no_team.status_code == 400
    assert sends == 0


@pytest.mark.asyncio
async def test_team_14_provider_failure_never_reports_invite_success(
    client, api_user, monkeypatch
):
    admin = await api_user("invite-provider")
    team = await create_team(client, admin)

    def fail_send(payload):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(teams_service.resend.Emails, "send", fail_send)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        response = await safe_client.post(
            "/teams/invite",
            json={"email": f"provider-{uuid4().hex}@example.com"},
            headers={**admin["headers"], "X-Team-Id": team["id"]},
        )
    assert response.status_code in {500, 502, 503}
    assert response.status_code != 200
    assert response.json()["success"] is False


@pytest.mark.asyncio
async def test_team_22_removed_member_immediately_loses_all_team_resource_access(
    client, api_user
):
    admin, member, team = await joined_team(client, api_user, "removed-access")
    team_headers = {**member["headers"], "X-Team-Id": team["id"]}
    created = await client.post(
        "/leads/",
        json={"name": "Private", "email": f"private-{uuid4().hex}@example.com"},
        headers=team_headers,
    )
    assert created.status_code == 201
    removed = await client.delete(
        f"/teams/{team['id']}/members/{member['id']}",
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    assert removed.status_code == 200
    assert (await client.get("/leads/", headers=team_headers)).status_code == 403
    assert (await client.get("/meetings/", headers=team_headers)).status_code == 403
    assert (await client.get("/proposals/", headers=team_headers)).status_code == 403


@pytest.mark.asyncio
async def test_team_24_concurrent_join_creates_only_one_membership(
    client, api_user
):
    admin = await api_user("join-race-admin")
    member = await api_user("join-race-member")
    team = await create_team(client, admin)
    import asyncio

    first, second = await asyncio.gather(
        client.post(
            "/teams/join",
            json={"invite_code": team["invite_code"]},
            headers=member["headers"],
        ),
        client.post(
            "/teams/join",
            json={"invite_code": team["invite_code"]},
            headers=member["headers"],
        ),
        return_exceptions=True,
    )
    responses = [item for item in (first, second) if not isinstance(item, Exception)]
    assert len(responses) == 2
    assert sorted(response.status_code for response in responses) in (
        [200, 400],
        [200, 409],
    )
    listed = await client.get("/teams/", headers=member["headers"])
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]].count(team["id"]) == 1


@pytest.mark.asyncio
async def test_bill_03_missing_price_is_controlled_without_stripe_call(
    client, api_user, monkeypatch
):
    user = await api_user("billing-missing-price")
    team = await create_team(client, user)
    monkeypatch.setattr(billing_service.settings, "stripe_growth_price", "")
    calls = 0

    async def should_not_call(**kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Stripe must not be called")

    monkeypatch.setattr(
        billing_service.stripe.checkout.Session, "create_async", should_not_call
    )
    response = await client.post(
        "/billing/checkout/growth",
        headers={**user["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code in {400, 422, 503}
    assert calls == 0


@pytest.mark.asyncio
async def test_bill_12_server_selects_price_and_team_metadata(
    client, api_user, monkeypatch
):
    user = await api_user("billing-trusted")
    team = await create_team(client, user)
    monkeypatch.setattr(billing_service.settings, "stripe_growth_price", "price_server")
    seen = {}

    customer_id = f"cus_{uuid4().hex}"

    async def fake_customer(**kwargs):
        assert kwargs["metadata"]["team_id"] == team["id"]
        return SimpleNamespace(id=customer_id)

    async def fake_session(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(url="https://checkout.example.invalid/session")

    monkeypatch.setattr(billing_service.stripe.Customer, "create_async", fake_customer)
    monkeypatch.setattr(
        billing_service.stripe.checkout.Session, "create_async", fake_session
    )
    response = await client.post(
        "/billing/checkout/growth?price=attacker&team_id=attacker",
        headers={**user["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 200, response.text
    assert seen["line_items"] == [{"price": "price_server", "quantity": 1}]
    assert seen["metadata"] == {"team_id": team["id"], "tier": "growth"}


@pytest.mark.asyncio
async def test_bill_11_nonmember_cannot_checkout_or_cancel(
    client, api_user, monkeypatch
):
    owner = await api_user("billing-owner")
    outsider = await api_user("billing-outsider")
    team = await create_team(client, owner)
    headers = {**outsider["headers"], "X-Team-Id": team["id"]}
    checkout = await client.post("/billing/checkout/growth", headers=headers)
    cancel = await client.post("/billing/cancel", headers=headers)
    assert checkout.status_code == cancel.status_code == 403
