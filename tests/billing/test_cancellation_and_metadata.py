from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models.subscription import Subscription
from app.routers import billing as billing_router
from app.services import billing_service
from tests.teams.test_team_api import create_team


async def _seed_subscription(
    team_id: str, *, status: str = "active", cancel_at_period_end: bool = False
) -> str:
    now = datetime.now(timezone.utc)
    subscription_id = f"sub_{uuid4().hex}"
    async with SessionLocal() as db:
        db.add(
            Subscription(
                team_id=UUID(team_id),
                stripe_subscription_id=subscription_id,
                stripe_price_id="price_growth_e2e",
                tier="growth",
                status=status,
                current_period_start=now - timedelta(days=1),
                current_period_end=now + timedelta(days=29),
                cancel_at_period_end=cancel_at_period_end,
            )
        )
        await db.commit()
    return subscription_id


async def _subscription(team_id: str) -> Subscription | None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Subscription).where(Subscription.team_id == UUID(team_id))
        )
        return result.scalars().first()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"tier": "growth"},
        {"team_id": "not-a-uuid", "tier": "growth"},
        {"team_id": "' OR '1'='1", "tier": "enterprise"},
        {"team_id": "<script>alert(1)</script>", "tier": "growth"},
        {"team_id": str(uuid4()), "tier": "growth"},
    ],
    ids=["missing-all", "missing-team", "invalid-uuid", "sql-like", "html", "unknown"],
)
async def test_bill_08_untrusted_team_metadata_is_controlled_and_cannot_mutate(
    client, api_user, monkeypatch, metadata
):
    user = await api_user("bill-08-owner")
    team = await create_team(client, user, "BILL-08 Protected")
    protected_id = await _seed_subscription(team["id"])
    event = {
        "id": f"evt_{uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "subscription": f"sub_{uuid4().hex}",
                "metadata": metadata,
            }
        },
    }
    monkeypatch.setattr(
        billing_router.stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: event,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        response = await safe_client.post(
            "/billing/webhook",
            content=b"synthetic-provider-event",
            headers={"stripe-signature": "verified-at-provider-boundary"},
        )

    protected = await _subscription(team["id"])
    assert response.status_code in {200, 400}
    assert protected is not None
    assert protected.stripe_subscription_id == protected_id
    assert protected.tier == "growth"
    assert protected.status == "active"


@pytest.mark.asyncio
async def test_bill_09_cancel_is_sent_once_and_status_reflects_period_end(
    client, api_user, monkeypatch
):
    user = await api_user("bill-09-cancel")
    team = await create_team(client, user, "BILL-09 Cancel")
    subscription_id = await _seed_subscription(team["id"])
    provider_calls = []

    async def cancel_once(requested_id, **kwargs):
        provider_calls.append((requested_id, kwargs))
        return {"id": requested_id, "cancel_at_period_end": True}

    monkeypatch.setattr(
        billing_service.stripe.Subscription, "modify_async", cancel_once
    )
    headers = {**user["headers"], "X-Team-Id": team["id"]}
    first = await client.post("/billing/cancel", headers=headers)
    second = await client.post("/billing/cancel", headers=headers)
    status = await client.get("/billing/status", headers=headers)

    assert first.status_code == second.status_code == status.status_code == 200
    assert provider_calls == [
        (subscription_id, {"cancel_at_period_end": True})
    ]
    assert status.json()["status"] == "active"
    assert status.json()["tier"] == "growth"
    assert status.json()["cancel_at_period_end"] is True
    assert status.json()["ends_at"] is not None


@pytest.mark.asyncio
async def test_bill_10_no_subscription_and_already_cancelled_are_idempotent(
    client, api_user, monkeypatch
):
    no_sub_user = await api_user("bill-10-none")
    no_sub_team = await create_team(client, no_sub_user, "BILL-10 None")
    cancelled_user = await api_user("bill-10-already")
    cancelled_team = await create_team(client, cancelled_user, "BILL-10 Already")
    await _seed_subscription(
        cancelled_team["id"], status="active", cancel_at_period_end=True
    )
    provider_calls = 0

    async def must_not_call(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("Idempotent cancellation must not call Stripe")

    monkeypatch.setattr(
        billing_service.stripe.Subscription, "modify_async", must_not_call
    )
    no_sub = await client.post(
        "/billing/cancel",
        headers={**no_sub_user["headers"], "X-Team-Id": no_sub_team["id"]},
    )
    already = await client.post(
        "/billing/cancel",
        headers={
            **cancelled_user["headers"],
            "X-Team-Id": cancelled_team["id"],
        },
    )

    assert no_sub.status_code in {200, 400, 409}
    assert already.status_code == 200
    assert provider_calls == 0
    row = await _subscription(cancelled_team["id"])
    assert row is not None and row.cancel_at_period_end is True


@pytest.mark.asyncio
async def test_bill_10_provider_failure_is_controlled_and_local_state_remains_truthful(
    client, api_user, monkeypatch
):
    user = await api_user("bill-10-provider")
    team = await create_team(client, user, "BILL-10 Provider")
    await _seed_subscription(team["id"])

    async def provider_failure(*args, **kwargs):
        raise RuntimeError("synthetic provider unavailable")

    monkeypatch.setattr(
        billing_service.stripe.Subscription, "modify_async", provider_failure
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        response = await safe_client.post(
            "/billing/cancel",
            headers={**user["headers"], "X-Team-Id": team["id"]},
        )

    assert response.status_code in {502, 503}
    body = response.json()
    assert "synthetic provider unavailable" not in str(body)
    row = await _subscription(team["id"])
    assert row is not None
    assert row.status == "active"
    assert row.cancel_at_period_end is False
