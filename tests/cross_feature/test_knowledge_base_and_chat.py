from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.database import SessionLocal
from app.models.chat import ChatMessage, ChatRole
from app.models.knowledge_base import KnowledgeAsset


async def context(client, api_user, prefix):
    user = await api_user(prefix)
    team = await client.post("/teams/", json={"name": f"{prefix} Team"}, headers=user["headers"])
    assert team.status_code == 201, team.text
    team_id = team.json()["data"]["id"]
    return user, team_id, {**user["headers"], "X-Team-Id": team_id}


async def seed_asset(team_id, title="Asset"):
    async with SessionLocal() as db:
        asset = KnowledgeAsset(
            team_id=UUID(team_id),
            title=title,
            description="Description",
            tags=["sales"],
            file_url="https://example.invalid/document.pdf",
            file_type="pdf",
            file_size=100,
            status="ready",
        )
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        return str(asset.id)


async def seed_message(user_id, team_id, sent_by=ChatRole.USER.value, content="Hello"):
    async with SessionLocal() as db:
        message = ChatMessage(
            user_id=UUID(user_id),
            team_id=UUID(team_id),
            sent_by=sent_by,
            content=content,
            metadata_log={},
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return str(message.id)


@pytest.mark.asyncio
async def test_kb_01_rejects_non_pdf_upload(client, api_user):
    _, _, headers = await context(client, api_user, "kb-type")
    response = await client.post(
        "/knowledge-base/upload",
        data={"title": "Not PDF"},
        files={"file": ("payload.txt", b"plain text", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["", " ", "\t"])
async def test_kb_02_rejects_blank_upload_title(client, api_user, title):
    _, _, headers = await context(client, api_user, "kb-title")
    response = await client.post(
        "/knowledge-base/upload",
        data={"title": title},
        files={"file": ("document.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers=headers,
    )
    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_kb_05_list_get_update_delete_asset(client, api_user):
    _, team_id, headers = await context(client, api_user, "kb-crud")
    asset_id = await seed_asset(team_id)
    listed = await client.get("/knowledge-base/", headers=headers)
    fetched = await client.get(f"/knowledge-base/{asset_id}", headers=headers)
    updated = await client.patch(
        f"/knowledge-base/{asset_id}",
        json={"title": "Updated", "tags": ["new"]},
        headers=headers,
    )
    deleted = await client.delete(f"/knowledge-base/{asset_id}", headers=headers)
    missing = await client.get(f"/knowledge-base/{asset_id}", headers=headers)
    assert listed.status_code == fetched.status_code == updated.status_code == deleted.status_code == 200
    assert updated.json()["data"]["title"] == "Updated"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_kb_08_cross_team_asset_crud_is_denied(client, api_user):
    _, owner_team, _ = await context(client, api_user, "kb-owner")
    _, _, stranger_headers = await context(client, api_user, "kb-stranger")
    asset_id = await seed_asset(owner_team, "Private")
    responses = [
        await client.get(f"/knowledge-base/{asset_id}", headers=stranger_headers),
        await client.patch(
            f"/knowledge-base/{asset_id}", json={"title": "Stolen"}, headers=stranger_headers
        ),
        await client.delete(f"/knowledge-base/{asset_id}", headers=stranger_headers),
    ]
    assert all(response.status_code in {403, 404} for response in responses)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["search", "ask"])
async def test_kb_search_and_ask_reject_blank_query(client, api_user, route):
    _, _, headers = await context(client, api_user, f"kb-{route}")
    response = await client.post(
        f"/knowledge-base/{route}", json={"query": "", "limit": 5}, headers=headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_kb_search_rejects_unbounded_limit(client, api_user):
    _, _, headers = await context(client, api_user, "kb-limit")
    response = await client.post(
        "/knowledge-base/search", json={"query": "pricing", "limit": 1000000}, headers=headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_02_list_get_edit_delete_user_message(client, api_user):
    user, team_id, headers = await context(client, api_user, "chat-crud")
    message_id = await seed_message(user["id"], team_id)
    listed = await client.get("/chat/", headers=headers)
    fetched = await client.get(f"/chat/{message_id}", headers=headers)
    edited = await client.patch(
        f"/chat/{message_id}", json={"content": "Edited"}, headers=headers
    )
    deleted = await client.delete(f"/chat/{message_id}", headers=headers)
    assert listed.status_code == fetched.status_code == edited.status_code == deleted.status_code == 200
    assert edited.json()["data"]["content"] == "Edited"
    assert edited.json()["data"]["metadata_log"]["edited"] is True


@pytest.mark.asyncio
async def test_chat_03_ai_message_cannot_be_edited(client, api_user):
    user, team_id, headers = await context(client, api_user, "chat-ai")
    message_id = await seed_message(user["id"], team_id, ChatRole.AI.value, "AI reply")
    response = await client.patch(
        f"/chat/{message_id}", json={"content": "Tampered"}, headers=headers
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_chat_08_cross_team_message_crud_is_denied(client, api_user):
    owner, owner_team, _ = await context(client, api_user, "chat-owner")
    _, _, stranger_headers = await context(client, api_user, "chat-stranger")
    message_id = await seed_message(owner["id"], owner_team)
    responses = [
        await client.get(f"/chat/{message_id}", headers=stranger_headers),
        await client.patch(
            f"/chat/{message_id}", json={"content": "Stolen"}, headers=stranger_headers
        ),
        await client.delete(f"/chat/{message_id}", headers=stranger_headers),
    ]
    assert all(response.status_code in {403, 404} for response in responses)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["", " ", "\t"])
async def test_chat_09_rejects_blank_messages(client, api_user, message):
    _, _, headers = await context(client, api_user, "chat-blank")
    response = await client.post("/chat/", json={"message": message}, headers=headers)
    assert response.status_code == 422
