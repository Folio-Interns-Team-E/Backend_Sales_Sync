from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.database import SessionLocal
from app.models.chat import ChatMessage, ChatRole
from tests.cross_feature.test_leads_meetings_proposals import team_context


async def _seed(
    user_id: str,
    team_id: str,
    content: str,
    sent_by: str = ChatRole.USER.value,
    created_at: datetime | None = None,
):
    async with SessionLocal() as db:
        message = ChatMessage(
            user_id=UUID(user_id),
            team_id=UUID(team_id),
            sent_by=sent_by,
            content=content,
            metadata_log={},
            created_at=created_at or datetime.now(timezone.utc),
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return str(message.id)


async def _join_owner_team(client, api_user, owner_headers, prefix):
    invite = await client.get(
        f"/teams/{owner_headers['X-Team-Id']}/invite-code",
        headers=owner_headers,
    )
    assert invite.status_code == 200, invite.text
    invite_code = invite.json()["data"]["invite_code"]
    member = await api_user(prefix)
    joined = await client.post(
        "/teams/join",
        json={"invite_code": invite_code},
        headers=member["headers"],
    )
    assert joined.status_code == 200, joined.text
    return member, {
        **member["headers"],
        "X-Team-Id": owner_headers["X-Team-Id"],
    }


@pytest.mark.asyncio
async def test_chat_05_cannot_edit_another_members_user_message(
    client, api_user
):
    owner, owner_headers = await team_context(client, api_user, "chat-author-owner")
    member, member_headers = await _join_owner_team(
        client, api_user, owner_headers, "chat-author-member"
    )
    message_id = await _seed(
        member["id"],
        owner_headers["X-Team-Id"],
        "Member-authored message",
    )

    response = await client.patch(
        f"/chat/{message_id}",
        json={"content": "Owner rewrote it"},
        headers=owner_headers,
    )
    fetched = await client.get(f"/chat/{message_id}", headers=member_headers)

    assert response.status_code in {403, 404}
    assert fetched.status_code == 200
    assert fetched.json()["data"]["content"] == "Member-authored message"
    assert fetched.json()["data"]["user_id"] == member["id"]
    assert owner["id"] != member["id"]


@pytest.mark.asyncio
async def test_chat_05_ai_message_cannot_be_edited(client, api_user):
    user, headers = await team_context(client, api_user, "chat-ai-edit")
    message_id = await _seed(
        user["id"],
        headers["X-Team-Id"],
        "AI-authored response",
        ChatRole.AI.value,
    )

    response = await client.patch(
        f"/chat/{message_id}",
        json={"content": "Tampered response"},
        headers=headers,
    )
    fetched = await client.get(f"/chat/{message_id}", headers=headers)

    assert response.status_code in {400, 403}
    assert fetched.status_code == 200
    assert fetched.json()["data"]["content"] == "AI-authored response"


@pytest.mark.asyncio
async def test_chat_06_delete_own_message_removes_only_target_and_preserves_order(
    client, api_user
):
    user, headers = await team_context(client, api_user, "chat-delete-own")
    now = datetime.now(timezone.utc)
    first = await _seed(
        user["id"], headers["X-Team-Id"], "First", created_at=now - timedelta(seconds=2)
    )
    target = await _seed(
        user["id"], headers["X-Team-Id"], "Delete", created_at=now - timedelta(seconds=1)
    )
    third = await _seed(
        user["id"], headers["X-Team-Id"], "Third", created_at=now
    )

    deleted = await client.delete(f"/chat/{target}", headers=headers)
    missing = await client.get(f"/chat/{target}", headers=headers)
    listed = await client.get("/chat/", headers=headers)

    assert deleted.status_code == 200
    assert missing.status_code == 404
    assert listed.status_code == 200
    remaining = listed.json()["data"]
    assert {row["id"] for row in remaining} == {first, third}
    assert [row["created_at"] for row in remaining] == sorted(
        [row["created_at"] for row in remaining], reverse=True
    )


@pytest.mark.asyncio
async def test_chat_07_cross_team_uuid_get_patch_delete_are_denied(
    client, api_user
):
    owner, owner_headers = await team_context(client, api_user, "chat-uuid-owner")
    _, stranger_headers = await team_context(client, api_user, "chat-uuid-stranger")
    message_id = await _seed(
        owner["id"], owner_headers["X-Team-Id"], "Private history"
    )

    responses = [
        await client.get(f"/chat/{message_id}", headers=stranger_headers),
        await client.patch(
            f"/chat/{message_id}",
            json={"content": "Stolen"},
            headers=stranger_headers,
        ),
        await client.delete(f"/chat/{message_id}", headers=stranger_headers),
    ]
    owner_fetch = await client.get(f"/chat/{message_id}", headers=owner_headers)

    assert all(response.status_code in {403, 404} for response in responses)
    assert owner_fetch.status_code == 200
    assert owner_fetch.json()["data"]["content"] == "Private history"
