from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models.chat import ChatMessage
from app.models.knowledge_base import KnowledgeAsset
from app.services import chat_service, knowledge_base_service
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from tests.test_core_resources import team_context


async def _upload(client, headers, content: bytes, title: str):
    return await client.post(
        "/knowledge-base/upload",
        data={"title": title},
        files={"file": ("fixture.pdf", content, "application/pdf")},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_kb_16_parser_resource_failure_is_contained_and_cleaned_up(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-parser-containment")
    puts, deletes = [], []
    monkeypatch.setattr(
        knowledge_base_service.s3_client,
        "put_object",
        lambda **kwargs: puts.append(kwargs) or {},
    )
    monkeypatch.setattr(
        knowledge_base_service.s3_client,
        "delete_object",
        lambda **kwargs: deletes.append(kwargs) or {},
    )

    async def resource_exhausted(self, asset, content):
        raise MemoryError("synthetic decompression limit exceeded")

    monkeypatch.setattr(
        KnowledgeBaseRAGService, "index_asset", resource_exhausted
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        response = await _upload(
            safe_client,
            headers,
            b"%PDF-1.7\nsynthetic decompression-bomb marker",
            "Bomb fixture",
        )

    assert response.status_code in {400, 413, 422, 500, 502, 503}
    assert "synthetic decompression limit exceeded" not in response.text
    assert len(puts) == len(deletes) == 1
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(KnowledgeAsset).where(
                    KnowledgeAsset.team_id == UUID(headers["X-Team-Id"])
                )
            )
        ).scalar_one_or_none()
    assert row is None or row.status == "failed"


@pytest.mark.asyncio
async def test_kb_17_upload_returns_before_slow_background_indexing_finishes(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-background-index")
    monkeypatch.setattr(
        knowledge_base_service.s3_client, "put_object", lambda **kwargs: {}
    )
    indexing_started = asyncio.Event()
    allow_indexing_to_finish = asyncio.Event()

    async def slow_index(self, asset, content):
        indexing_started.set()
        await allow_indexing_to_finish.wait()
        asset.status = "ready"
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    monkeypatch.setattr(KnowledgeBaseRAGService, "index_asset", slow_index)
    upload_task = asyncio.create_task(
        _upload(
            client,
            headers,
            b"%PDF-1.4\nlarge-document-fixture",
            "Large document",
        )
    )
    await asyncio.wait_for(indexing_started.wait(), timeout=2)
    done, _ = await asyncio.wait({upload_task}, timeout=0.2)
    returned_before_indexing = upload_task in done
    allow_indexing_to_finish.set()
    response = await asyncio.wait_for(upload_task, timeout=2)

    assert returned_before_indexing
    assert response.status_code in {200, 201, 202}
    assert response.json()["data"]["status"] in {"processing", "queued"}


@pytest.mark.asyncio
async def test_kb_17_large_corpus_search_is_bounded_and_respects_max_results(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-large-corpus")
    calls = []

    async def bounded(self, vector, namespace, top_k):
        calls.append((namespace, top_k))
        return {"matches": []}

    monkeypatch.setattr(KnowledgeBaseRAGService, "_pinecone_query", bounded)
    response = await client.post(
        "/knowledge-base/search",
        json={"query": "enterprise pricing", "limit": 20},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["sources"] == []
    assert calls == [(headers["X-Team-Id"], 20)]


@pytest.mark.asyncio
async def test_chat_01_normal_message_persists_user_and_ai_once(
    client, api_user, monkeypatch
):
    user, headers = await team_context(client, api_user, "chat-normal")

    async def extract_action(self, message, icp):
        return {"action": "NORMAL", "parameters": {}}

    async def grounded(self, team_id, query, limit=5):
        return {
            "answer": "Grounded draft",
            "sources": [{"asset_id": "synthetic"}],
        }

    async def finalize(
        self, user_prompt, execution_result, team_id, messages_history, user_info
    ):
        return "Here is the final grounded reply."

    monkeypatch.setattr(
        chat_service.SupervisorAgent, "extract_action", extract_action
    )
    monkeypatch.setattr(chat_service.SupervisorAgent, "run", finalize)
    monkeypatch.setattr(KnowledgeBaseRAGService, "answer_query", grounded)
    response = await client.post(
        "/chat/", json={"message": "Summarize our pricing."}, headers=headers
    )
    listed = await client.get("/chat/", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["reply"] == "Here is the final grounded reply."
    assert listed.status_code == 200
    messages = listed.json()["data"]
    assert len(messages) == 2
    assert {message["sent_by"] for message in messages} == {"user", "ai"}
    assert sum(message["content"] == "Summarize our pricing." for message in messages) == 1
    assert (
        sum(
            message["content"] == "Here is the final grounded reply."
            for message in messages
        )
        == 1
    )
    assert all(message["user_id"] == user["id"] for message in messages)
