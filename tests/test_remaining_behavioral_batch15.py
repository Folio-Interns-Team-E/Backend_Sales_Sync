from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.chat import ChatMessage, ChatRole
from app.services.chat_service import ChatService
from tests.test_core_resources import team_context


async def _seed_message(
    user_id: str,
    team_id: str,
    content: str,
    sent_by: str,
    created_at: datetime,
    metadata: dict | None = None,
):
    async with SessionLocal() as db:
        message = ChatMessage(
            user_id=UUID(user_id),
            team_id=UUID(team_id),
            sent_by=sent_by,
            content=content,
            metadata_log=metadata or {},
            created_at=created_at,
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return str(message.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["", " ", "\t\n"], ids=["empty", "space", "whitespace"])
async def test_chat_02_rejects_blank_messages_before_ai_call(
    client, api_user, monkeypatch, message
):
    _, headers = await team_context(client, api_user, "chat-blank-deep")
    calls = []

    async def should_not_send(self, user_id, team_id, supplied):
        calls.append(supplied)
        return "unexpected"

    monkeypatch.setattr(ChatService, "send_message", should_not_send)
    response = await client.post("/chat/", json={"message": message}, headers=headers)

    assert response.status_code == 422
    assert calls == []


@pytest.mark.asyncio
async def test_chat_02_rejects_excessively_long_message_before_ai_call(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "chat-too-long")
    calls = []

    async def should_not_send(self, user_id, team_id, supplied):
        calls.append(len(supplied))
        return "unexpected"

    monkeypatch.setattr(ChatService, "send_message", should_not_send)
    response = await client.post(
        "/chat/", json={"message": "x" * 100_001}, headers=headers
    )

    assert response.status_code in {413, 422}
    assert calls == []


@pytest.mark.asyncio
async def test_chat_02_unicode_message_round_trips_without_corruption(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "chat-unicode")
    supplied = "مرحبا — こんにちは — café — 🚀"
    calls = []

    async def echo(self, user_id, team_id, message):
        calls.append(message)
        return f"Received: {message}"

    monkeypatch.setattr(ChatService, "send_message", echo)
    response = await client.post(
        "/chat/", json={"message": supplied}, headers=headers
    )

    assert response.status_code == 200
    assert calls == [supplied]
    assert response.json()["data"]["reply"] == f"Received: {supplied}"


@pytest.mark.asyncio
async def test_chat_03_history_and_get_are_team_scoped_chronological_with_metadata(
    client, api_user
):
    user, headers = await team_context(client, api_user, "chat-history")
    _, stranger_headers = await team_context(client, api_user, "chat-history-stranger")
    now = datetime.now(timezone.utc)
    first_id = await _seed_message(
        user["id"],
        headers["X-Team-Id"],
        "First question",
        ChatRole.USER.value,
        now - timedelta(seconds=2),
        {"sequence": 1},
    )
    second_id = await _seed_message(
        user["id"],
        headers["X-Team-Id"],
        "First answer",
        ChatRole.AI.value,
        now - timedelta(seconds=1),
        {"sequence": 2},
    )
    third_id = await _seed_message(
        user["id"],
        headers["X-Team-Id"],
        "Follow-up",
        ChatRole.USER.value,
        now,
        {"sequence": 3},
    )
    await _seed_message(
        (await api_user("chat-outsider-message"))["id"],
        stranger_headers["X-Team-Id"],
        "Other team",
        ChatRole.USER.value,
        now + timedelta(seconds=1),
    )

    listed = await client.get("/chat/", headers=headers)
    fetched = await client.get(f"/chat/{second_id}", headers=headers)

    assert listed.status_code == fetched.status_code == 200
    messages = listed.json()["data"]
    assert [message["id"] for message in messages] == [first_id, second_id, third_id]
    assert [message["metadata_log"]["sequence"] for message in messages] == [1, 2, 3]
    assert fetched.json()["data"]["content"] == "First answer"
    assert fetched.json()["data"]["team_id"] == headers["X-Team-Id"]


@pytest.mark.asyncio
async def test_chat_04_edit_own_message_persists_and_history_refreshes(
    client, api_user
):
    user, headers = await team_context(client, api_user, "chat-edit-own")
    message_id = await _seed_message(
        user["id"],
        headers["X-Team-Id"],
        "Original wording",
        ChatRole.USER.value,
        datetime.now(timezone.utc),
    )

    updated = await client.patch(
        f"/chat/{message_id}",
        json={"content": "Corrected wording"},
        headers=headers,
    )
    fetched = await client.get(f"/chat/{message_id}", headers=headers)
    listed = await client.get("/chat/", headers=headers)

    assert updated.status_code == fetched.status_code == listed.status_code == 200
    assert updated.json()["data"]["content"] == "Corrected wording"
    assert updated.json()["data"]["metadata_log"]["edited"] is True
    assert fetched.json()["data"]["content"] == "Corrected wording"
    history_row = next(
        row for row in listed.json()["data"] if row["id"] == message_id
    )
    assert history_row["content"] == "Corrected wording"
    assert history_row["metadata_log"]["edited"] is True
