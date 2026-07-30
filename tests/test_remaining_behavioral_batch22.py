from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.database import SessionLocal
from app.models.subscription import Subscription
from app.services import billing_service
from tests.test_teams import create_team


async def _join_as_rep(client, api_user, prefix: str):
    admin = await api_user(f"{prefix}-admin")
    rep = await api_user(f"{prefix}-rep")
    team = await create_team(client, admin, f"{prefix} Team")
    joined = await client.post(
        "/teams/join",
        json={"invite_code": team["invite_code"]},
        headers=rep["headers"],
    )
    assert joined.status_code == 200, joined.text
    return admin, rep, team


async def _seed_active_subscription(team_id: str):
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        db.add(
            Subscription(
                team_id=UUID(team_id),
                stripe_subscription_id=f"sub_{uuid4().hex}",
                stripe_price_id="price_growth_e2e",
                tier="growth",
                status="active",
                current_period_start=now - timedelta(days=1),
                current_period_end=now + timedelta(days=29),
                cancel_at_period_end=False,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_bill_11_rep_cannot_start_checkout_or_cancel_subscription(
    client, api_user, monkeypatch
):
    _, rep, team = await _join_as_rep(client, api_user, "bill-11")
    await _seed_active_subscription(team["id"])
    provider_calls = []
    monkeypatch.setattr(
        billing_service.settings, "stripe_growth_price", "price_growth_e2e"
    )

    async def provider_call(*args, **kwargs):
        provider_calls.append((args, kwargs))
        return SimpleNamespace(
            id=f"provider_{uuid4().hex}",
            url="https://checkout.stripe.invalid/session",
        )

    monkeypatch.setattr(
        billing_service.stripe.Customer, "create_async", provider_call
    )
    monkeypatch.setattr(
        billing_service.stripe.checkout.Session, "create_async", provider_call
    )
    monkeypatch.setattr(
        billing_service.stripe.Subscription, "modify_async", provider_call
    )
    headers = {**rep["headers"], "X-Team-Id": team["id"]}

    checkout = await client.post("/billing/checkout/growth", headers=headers)
    cancel = await client.post("/billing/cancel", headers=headers)

    assert checkout.status_code == cancel.status_code == 403
    assert provider_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tier", "trusted_price"),
    [("growth", "price_growth_trusted"), ("enterprise", "price_enterprise_trusted")],
)
async def test_bill_12_client_cannot_override_price_team_customer_or_tier(
    client, api_user, monkeypatch, tier, trusted_price
):
    user = await api_user(f"bill-12-{tier}")
    team = await create_team(client, user, f"BILL-12 {tier}")
    monkeypatch.setattr(
        billing_service.settings, f"stripe_{tier}_price", trusted_price
    )
    seen = {}
    trusted_customer = f"cus_{uuid4().hex}"

    async def create_customer(**kwargs):
        assert kwargs == {
            "metadata": {"team_id": team["id"]},
            "name": f"BILL-12 {tier}",
        }
        return SimpleNamespace(id=trusted_customer)

    async def create_session(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.invalid/trusted")

    monkeypatch.setattr(
        billing_service.stripe.Customer, "create_async", create_customer
    )
    monkeypatch.setattr(
        billing_service.stripe.checkout.Session, "create_async", create_session
    )
    response = await client.post(
        (
            f"/billing/checkout/{tier}"
            "?price=price_attacker&tier=enterprise&team_id=attacker"
            "&customer=cus_attacker&success_url=https://attacker.invalid"
        ),
        json={
            "price": "price_attacker",
            "tier": "enterprise",
            "team_id": "attacker",
            "customer": "cus_attacker",
        },
        headers={**user["headers"], "X-Team-Id": team["id"]},
    )

    assert response.status_code == 200, response.text
    assert seen["customer"] == trusted_customer
    assert seen["line_items"] == [{"price": trusted_price, "quantity": 1}]
    assert seen["metadata"] == {"team_id": team["id"], "tier": tier}
