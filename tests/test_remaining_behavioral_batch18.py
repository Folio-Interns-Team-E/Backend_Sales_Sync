from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.chat import ChatMessage, ChatRole
from app.models.subscription import Subscription
from app.services import chat_service
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from tests.test_core_resources import team_context


async def _messages(team_id: str):
    async with SessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(ChatMessage).where(ChatMessage.team_id == UUID(team_id))
                )
            ).scalars().all()
        )


@pytest.mark.asyncio
async def test_chat_12_ai_metadata_is_accurate_and_contains_no_sensitive_prompt_data(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "chat-metadata")
    secret_marker = "secret-prompt-marker"

    async def normal(self, message, icp):
        return {"action": "NORMAL", "parameters": {}}

    async def no_sources(self, team_id, query, limit=5):
        return {"answer": "", "sources": []}

    async def final(
        self, user_prompt, execution_result, team_id, messages_history, user_info
    ):
        return "Safe response"

    monkeypatch.setattr(chat_service.SupervisorAgent, "extract_action", normal)
    monkeypatch.setattr(chat_service.SupervisorAgent, "run", final)
    monkeypatch.setattr(KnowledgeBaseRAGService, "answer_query", no_sources)
    response = await client.post(
        "/chat/",
        json={"message": f"Summarize pricing without logging {secret_marker}"},
        headers=headers,
    )

    assert response.status_code == 200
    rows = await _messages(headers["X-Team-Id"])
    ai_row = next(row for row in rows if row.sent_by == ChatRole.AI.value)
    metadata = ai_row.metadata_log
    assert isinstance(metadata.get("token_count"), int)
    assert metadata["token_count"] > 0
    assert isinstance(metadata.get("latency_ms"), int | float)
    assert metadata["latency_ms"] >= 0
    assert metadata.get("model")
    serialized = str(metadata)
    assert secret_marker not in serialized
    assert "e2e-only-jwt-secret" not in serialized


async def _seed_subscription(team_id: str, status: str, tier: str, cancel: bool):
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        subscription = Subscription(
            team_id=UUID(team_id),
            stripe_subscription_id=f"sub_{uuid4().hex}",
            stripe_price_id=f"price_{tier}",
            tier=tier,
            status=status,
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
            cancel_at_period_end=cancel,
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        return subscription.current_period_end


@pytest.mark.asyncio
async def test_bill_01_no_subscription_returns_free_active_defaults(client, api_user):
    _, headers = await team_context(client, api_user, "bill-free")
    response = await client.get("/billing/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "tier": "free",
        "status": "active",
        "ends_at": None,
        "cancel_at_period_end": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "tier", "cancel"),
    [
        ("active", "growth", False),
        ("canceled", "enterprise", True),
        ("past_due", "growth", False),
    ],
    ids=["active", "canceled", "past-due"],
)
async def test_bill_01_subscription_status_round_trips(
    client, api_user, status, tier, cancel
):
    _, headers = await team_context(client, api_user, f"bill-{status}")
    expected_end = await _seed_subscription(
        headers["X-Team-Id"], status, tier, cancel
    )
    response = await client.get("/billing/status", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == tier
    assert data["status"] == status
    assert data["cancel_at_period_end"] is cancel
    assert datetime.fromisoformat(data["ends_at"]).replace(
        tzinfo=timezone.utc
    ) == expected_end.replace(tzinfo=timezone.utc)
