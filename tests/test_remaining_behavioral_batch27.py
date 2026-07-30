from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from uuid import uuid4

import pytest

from app.services import chat_service, knowledge_base_service
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from tests.test_core_resources import create_lead, team_context


@pytest.mark.asyncio
async def test_core_15_concurrent_list_search_chat_and_upload_do_not_starve(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "core-15")
    for index in range(5):
        await create_lead(client, headers, f"Concurrent{index}")

    monkeypatch.setattr(
        knowledge_base_service.s3_client, "put_object", lambda **kwargs: {}
    )

    async def index_without_provider(self, asset, content):
        asset.status = "ready"
        asset.chunk_count = 0
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    async def empty_vector_results(self, vector, namespace, top_k):
        return {"matches": []}

    async def normal_action(self, message, icp):
        return {"action": "NORMAL", "parameters": {}}

    async def no_sources(self, team_id, query, limit=5):
        return {"answer": "", "sources": []}

    async def final_reply(
        self, user_prompt, execution_result, team_id, messages_history, user_info
    ):
        return f"Processed {user_prompt}"

    monkeypatch.setattr(KnowledgeBaseRAGService, "index_asset", index_without_provider)
    monkeypatch.setattr(
        KnowledgeBaseRAGService, "_pinecone_query", empty_vector_results
    )
    monkeypatch.setattr(
        chat_service.SupervisorAgent, "extract_action", normal_action
    )
    monkeypatch.setattr(chat_service.SupervisorAgent, "run", final_reply)
    monkeypatch.setattr(KnowledgeBaseRAGService, "answer_query", no_sources)

    async def list_request(index):
        return "list", index, await client.get("/leads/", headers=headers)

    async def search_request(index):
        return (
            "search",
            index,
            await client.post(
                "/knowledge-base/search",
                json={"query": f"pricing {index}", "limit": 5},
                headers=headers,
            ),
        )

    async def chat_request(index):
        return (
            "chat",
            index,
            await client.post(
                "/chat/",
                json={"message": f"concurrent message {index}"},
                headers=headers,
            ),
        )

    async def upload_request(index):
        return (
            "upload",
            index,
            await client.post(
                "/knowledge-base/upload",
                data={"title": f"Concurrent document {index}"},
                files={
                    "file": (
                        f"concurrent-{index}.pdf",
                        b"%PDF-1.4\nsynthetic load fixture",
                        "application/pdf",
                    )
                },
                headers=headers,
            ),
        )

    tasks = []
    for index in range(6):
        tasks.extend(
            [
                list_request(index),
                search_request(index),
                chat_request(index),
                upload_request(index),
            ]
        )

    started = perf_counter()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
    elapsed = perf_counter() - started

    failures = [
        (kind, index, response.status_code, response.text[:200])
        for kind, index, response in results
        if response.status_code not in ({201} if kind == "upload" else {200})
    ]
    assert failures == []
    assert elapsed < 10

    lists = [response for kind, _, response in results if kind == "list"]
    assert all(len(response.json()["data"]) == 5 for response in lists)
    searches = [response for kind, _, response in results if kind == "search"]
    assert all(response.json()["data"]["sources"] == [] for response in searches)

    chat_history = await client.get("/chat/", headers=headers)
    assets = await client.get("/knowledge-base/", headers=headers)
    assert chat_history.status_code == assets.status_code == 200
    assert len(chat_history.json()["data"]) == 12
    assert len(assets.json()["data"]) == 6


@pytest.mark.asyncio
async def test_core_16_external_failures_have_correlated_redacted_logs(
    client, api_user, monkeypatch, caplog
):
    _, headers = await team_context(client, api_user, "core-16")
    secret_marker = f"provider-secret-{uuid4().hex}"

    def provider_failure(**kwargs):
        raise RuntimeError(f"upstream rejected credential {secret_marker}")

    monkeypatch.setattr(
        knowledge_base_service.s3_client, "put_object", provider_failure
    )
    caplog.set_level(logging.INFO)
    response = await client.post(
        "/knowledge-base/upload",
        data={"title": "Redaction check"},
        files={
            "file": (
                "redaction.pdf",
                b"%PDF-1.4\nredaction fixture",
                "application/pdf",
            )
        },
        headers=headers,
    )

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    correlation_id = (
        response.headers.get("x-request-id")
        or response.headers.get("x-correlation-id")
    )
    problems = []
    if not correlation_id:
        problems.append("response has no request/correlation identifier")
    elif correlation_id not in log_text:
        problems.append("response correlation identifier is absent from logs")
    if secret_marker in log_text:
        problems.append("provider credential marker leaked into logs")
    if secret_marker in response.text:
        problems.append("provider credential marker leaked into the response")
    if headers["X-Team-Id"] in log_text:
        problems.append("raw team identifier was logged without redaction")

    assert response.status_code in {500, 502, 503}
    assert problems == []
