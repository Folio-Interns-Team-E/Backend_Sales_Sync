from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.subscription import Subscription
from app.routers import billing as billing_router
from tests.test_teams import create_team


def _signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    timestamp = timestamp or int(time.time())
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


async def _subscriptions(team_id: str) -> list[Subscription]:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Subscription).where(Subscription.team_id == UUID(team_id))
        )
        return list(result.scalars().all())


async def _post_provider_event(client, monkeypatch, event: dict):
    monkeypatch.setattr(
        billing_router.stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: event,
    )
    return await client.post(
        "/billing/webhook",
        content=json.dumps(event).encode(),
        headers={"stripe-signature": "verified-at-provider-boundary"},
    )


@pytest.mark.asyncio
async def test_bill_05_checkout_completed_creates_exact_subscription_state(
    client, api_user, monkeypatch
):
    user = await api_user("bill-05-checkout")
    team = await create_team(client, user, "BILL-05 Checkout")
    now = int(datetime.now(timezone.utc).timestamp())
    event = {
        "id": f"evt_{uuid4().hex}",
        "created": now,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": f"cus_{uuid4().hex}",
                "subscription": f"sub_{uuid4().hex}",
                "metadata": {"team_id": team["id"], "tier": "growth"},
            }
        },
    }

    response = await _post_provider_event(client, monkeypatch, event)
    rows = await _subscriptions(team["id"])

    assert response.status_code == 200, response.text
    assert len(rows) == 1
    row = rows[0]
    assert row.stripe_subscription_id == event["data"]["object"]["subscription"]
    assert row.tier == "growth"
    assert row.status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "provider_status", "expected_status"),
    [
        ("customer.subscription.created", "trialing", "trialing"),
        ("customer.subscription.updated", "past_due", "past_due"),
        ("customer.subscription.deleted", "canceled", "canceled"),
    ],
)
async def test_bill_05_subscription_events_upsert_exact_provider_state(
    client, api_user, monkeypatch, event_type, provider_status, expected_status
):
    user = await api_user(f"bill-05-{provider_status}")
    team = await create_team(client, user, f"BILL-05 {provider_status}")
    now = int(datetime.now(timezone.utc).timestamp())
    subscription_id = f"sub_{uuid4().hex}"
    event = {
        "id": f"evt_{uuid4().hex}",
        "created": now,
        "type": event_type,
        "data": {
            "object": {
                "id": subscription_id,
                "customer": f"cus_{uuid4().hex}",
                "status": provider_status,
                "cancel_at_period_end": event_type == "customer.subscription.deleted",
                "canceled_at": now if event_type == "customer.subscription.deleted" else None,
                "current_period_start": now - 60,
                "current_period_end": now + 3600,
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_growth_e2e",
                                "metadata": {"tier": "growth"},
                            }
                        }
                    ]
                },
                "metadata": {"team_id": team["id"], "tier": "growth"},
            }
        },
    }

    response = await _post_provider_event(client, monkeypatch, event)
    rows = await _subscriptions(team["id"])

    assert response.status_code == 200, response.text
    assert len(rows) == 1
    assert rows[0].stripe_subscription_id == subscription_id
    assert rows[0].status == expected_status
    assert rows[0].cancel_at_period_end == (
        event_type == "customer.subscription.deleted"
    )


@pytest.mark.asyncio
async def test_bill_06_missing_invalid_and_modified_signatures_do_not_mutate(
    client, api_user, monkeypatch
):
    user = await api_user("bill-06-signature")
    team = await create_team(client, user, "BILL-06 Signature")
    secret = "whsec_e2e_only"
    monkeypatch.setattr(billing_router.settings, "stripe_webhook_secret", secret)
    event = {
        "id": f"evt_{uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "subscription": f"sub_{uuid4().hex}",
                "metadata": {"team_id": team["id"], "tier": "growth"},
            }
        },
    }
    original = json.dumps(event, separators=(",", ":")).encode()
    modified = original.replace(b'"growth"', b'"enterprise"')

    missing = await client.post("/billing/webhook", content=original)
    invalid = await client.post(
        "/billing/webhook",
        content=original,
        headers={"stripe-signature": "t=1,v1=invalid"},
    )
    tampered = await client.post(
        "/billing/webhook",
        content=modified,
        headers={"stripe-signature": _signature(original, secret)},
    )

    assert missing.status_code == invalid.status_code == tampered.status_code == 400
    assert await _subscriptions(team["id"]) == []


@pytest.mark.asyncio
async def test_bill_07_duplicate_and_older_events_cannot_duplicate_or_regress_state(
    client, api_user, monkeypatch
):
    user = await api_user("bill-07-order")
    team = await create_team(client, user, "BILL-07 Ordering")
    subscription_id = f"sub_{uuid4().hex}"
    base = int(datetime.now(timezone.utc).timestamp())

    def event(event_id: str, created: int, status: str) -> dict:
        return {
            "id": event_id,
            "created": created,
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": subscription_id,
                    "status": status,
                    "cancel_at_period_end": status == "canceled",
                    "current_period_start": base - 60,
                    "current_period_end": base + 3600,
                    "items": {
                        "data": [
                            {
                                "price": {
                                    "id": "price_growth_e2e",
                                    "metadata": {"tier": "growth"},
                                }
                            }
                        ]
                    },
                    "metadata": {"team_id": team["id"], "tier": "growth"},
                }
            },
        }

    newest = event(f"evt_{uuid4().hex}", base + 10, "active")
    older = event(f"evt_{uuid4().hex}", base, "past_due")
    responses = [
        await _post_provider_event(client, monkeypatch, newest),
        await _post_provider_event(client, monkeypatch, newest),
        await _post_provider_event(client, monkeypatch, older),
    ]
    rows = await _subscriptions(team["id"])

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert len(rows) == 1
    assert rows[0].stripe_subscription_id == subscription_id
    assert rows[0].status == "active"
