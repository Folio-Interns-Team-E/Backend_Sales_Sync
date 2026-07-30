from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import billing_service
from tests.test_teams import create_team


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tier", "configured_price"),
    (("growth", "price_growth_e2e"), ("enterprise", "price_enterprise_e2e")),
)
async def test_bill_02_checkout_uses_configured_price_team_metadata_and_return_urls(
    client, api_user, monkeypatch, tier, configured_price
):
    user = await api_user(f"bill-02-{tier}")
    team = await create_team(client, user, f"BILL-02 {tier}")
    monkeypatch.setattr(
        billing_service.settings, f"stripe_{tier}_price", configured_price
    )
    customer_calls = []
    session_calls = []

    async def create_customer(**kwargs):
        customer_calls.append(kwargs)
        return SimpleNamespace(id=f"cus_{uuid4().hex}")

    async def create_session(**kwargs):
        session_calls.append(kwargs)
        return SimpleNamespace(url=f"https://checkout.stripe.invalid/{tier}")

    monkeypatch.setattr(
        billing_service.stripe.Customer, "create_async", create_customer
    )
    monkeypatch.setattr(
        billing_service.stripe.checkout.Session, "create_async", create_session
    )

    response = await client.post(
        f"/billing/checkout/{tier}",
        headers={**user["headers"], "X-Team-Id": team["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"checkout_url": f"https://checkout.stripe.invalid/{tier}"}
    assert customer_calls == [
        {"metadata": {"team_id": team["id"]}, "name": f"BILL-02 {tier}"}
    ]
    assert len(session_calls) == 1
    checkout = session_calls[0]
    assert checkout["line_items"] == [{"price": configured_price, "quantity": 1}]
    assert checkout["metadata"] == {"team_id": team["id"], "tier": tier}
    assert checkout["mode"] == "subscription"
    assert checkout["success_url"] in {
        f"{origin}/billing/success" for origin in billing_service.settings.frontend_origins
    }
    assert checkout["cancel_url"] in {
        f"{origin}/billing/cancel" for origin in billing_service.settings.frontend_origins
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["free", "premium", "GROWTH", "../growth", ""])
async def test_bill_03_invalid_tier_is_controlled_and_never_calls_stripe(
    client, api_user, monkeypatch, tier
):
    user = await api_user("bill-03-invalid")
    team = await create_team(client, user, "BILL-03 Invalid Tier")
    stripe_calls = 0

    async def must_not_call(**kwargs):
        nonlocal stripe_calls
        stripe_calls += 1
        raise AssertionError("Stripe must not be called for an invalid tier")

    monkeypatch.setattr(
        billing_service.stripe.checkout.Session, "create_async", must_not_call
    )
    response = await client.post(
        f"/billing/checkout/{tier}",
        headers={**user["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code in {400, 404, 422}
    assert stripe_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["growth", "enterprise"])
async def test_bill_03_missing_price_is_controlled_and_never_calls_stripe(
    client, api_user, monkeypatch, tier
):
    user = await api_user(f"bill-03-missing-{tier}")
    team = await create_team(client, user, "BILL-03 Missing Price")
    monkeypatch.setattr(billing_service.settings, f"stripe_{tier}_price", "")
    stripe_calls = 0

    async def must_not_call(**kwargs):
        nonlocal stripe_calls
        stripe_calls += 1
        raise AssertionError("Stripe must not be called without a configured price")

    monkeypatch.setattr(
        billing_service.stripe.checkout.Session, "create_async", must_not_call
    )
    response = await client.post(
        f"/billing/checkout/{tier}",
        headers={**user["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code in {400, 422, 503}
    assert stripe_calls == 0
