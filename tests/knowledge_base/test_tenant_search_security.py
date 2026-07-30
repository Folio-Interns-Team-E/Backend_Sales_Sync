from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.knowledge_base import KnowledgeAsset, KnowledgeAssetChunk
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from tests.cross_feature.test_leads_meetings_proposals import team_context


async def _seed_indexed(team_id: str, title: str, content: str):
    async with SessionLocal() as db:
        asset = KnowledgeAsset(
            team_id=UUID(team_id),
            title=title,
            description=f"{title} description",
            tags=["search"],
            file_url=f"https://example.invalid/{title}.pdf",
            source_url=f"https://example.invalid/{title}.pdf",
            file_type="pdf",
            file_size=100,
            status="ready",
            embedding_id="indexed",
            chunk_count=1,
        )
        db.add(asset)
        await db.flush()
        chunk = KnowledgeAssetChunk(
            team_id=UUID(team_id),
            asset_id=asset.id,
            chunk_index=0,
            content=content,
            pinecone_vector_id=f"{asset.id}:0",
            token_count=len(content.split()),
        )
        db.add(chunk)
        await db.commit()
        return str(asset.id), chunk.pinecone_vector_id


@pytest.mark.asyncio
async def test_kb_10_cross_team_crud_and_list_are_denied(client, api_user):
    _, owner_headers = await team_context(client, api_user, "kb-tenant-owner")
    _, stranger_headers = await team_context(client, api_user, "kb-tenant-stranger")
    asset_id, _ = await _seed_indexed(
        owner_headers["X-Team-Id"], "OwnerSecret", "Owner-only content"
    )

    listed = await client.get("/knowledge-base/", headers=stranger_headers)
    responses = [
        await client.get(f"/knowledge-base/{asset_id}", headers=stranger_headers),
        await client.patch(
            f"/knowledge-base/{asset_id}",
            json={"title": "Stolen"},
            headers=stranger_headers,
        ),
        await client.delete(f"/knowledge-base/{asset_id}", headers=stranger_headers),
    ]

    assert listed.status_code == 200
    assert listed.json()["data"] == []
    assert all(response.status_code in {403, 404} for response in responses)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["search", "ask"])
async def test_kb_10_search_and_ask_reject_cross_team_vector_matches(
    client, api_user, monkeypatch, route
):
    _, owner_headers = await team_context(client, api_user, f"kb-rag-owner-{route}")
    _, stranger_headers = await team_context(client, api_user, f"kb-rag-stranger-{route}")
    _, owner_vector = await _seed_indexed(
        owner_headers["X-Team-Id"],
        "Confidential",
        "Private acquisition plan and secret pricing.",
    )

    async def wrong_namespace_result(self, vector, namespace, top_k):
        assert namespace == stranger_headers["X-Team-Id"]
        return {
            "matches": [
                {
                    "id": owner_vector,
                    "score": 0.99,
                    "metadata": {
                        "asset_title": "Confidential",
                        "chunk_index": 0,
                    },
                }
            ]
        }

    monkeypatch.setattr(
        KnowledgeBaseRAGService, "_pinecone_query", wrong_namespace_result
    )
    response = await client.post(
        f"/knowledge-base/{route}",
        json={"query": "secret pricing", "limit": 5},
        headers=stranger_headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sources"] == []
    assert "Private acquisition" not in response.text
    assert "Confidential" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 3, 20])
async def test_kb_11_semantic_search_preserves_rank_and_respects_limit(
    client, api_user, monkeypatch, limit
):
    _, headers = await team_context(client, api_user, f"kb-ranked-{limit}")
    seeded = [
        await _seed_indexed(
            headers["X-Team-Id"], "Best", "Enterprise pricing and discount policy"
        ),
        await _seed_indexed(
            headers["X-Team-Id"], "Second", "Pricing overview for customers"
        ),
        await _seed_indexed(
            headers["X-Team-Id"], "Third", "General commercial notes"
        ),
    ]
    matches = [
        {
            "id": seeded[0][1],
            "score": 0.95,
            "metadata": {"asset_title": "Best", "chunk_index": 0},
        },
        {
            "id": seeded[1][1],
            "score": 0.80,
            "metadata": {"asset_title": "Second", "chunk_index": 0},
        },
        {
            "id": seeded[2][1],
            "score": 0.60,
            "metadata": {"asset_title": "Third", "chunk_index": 0},
        },
    ]
    calls = []

    async def ranked(self, vector, namespace, top_k):
        calls.append((namespace, top_k))
        return {"matches": matches[:top_k]}

    monkeypatch.setattr(KnowledgeBaseRAGService, "_pinecone_query", ranked)
    response = await client.post(
        "/knowledge-base/search",
        json={"query": "enterprise pricing", "limit": limit},
        headers=headers,
    )

    assert response.status_code == 200
    sources = response.json()["data"]["sources"]
    assert [source["asset_title"] for source in sources] == [
        "Best",
        "Second",
        "Third",
    ][:limit]
    assert [source["score"] for source in sources] == sorted(
        [source["score"] for source in sources], reverse=True
    )
    assert all(source["content"] and source["chunk_index"] == 0 for source in sources)
    assert calls == [(headers["X-Team-Id"], limit)]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["search", "ask"])
@pytest.mark.parametrize(
    ("query", "limit"),
    [
        ("", 5),
        ("   \t", 5),
        ("pricing", 0),
        ("pricing", -1),
        ("pricing", 1_000_000),
    ],
    ids=["empty-query", "whitespace-query", "zero-limit", "negative-limit", "huge-limit"],
)
async def test_kb_12_rejects_invalid_query_and_limit_before_provider_call(
    client, api_user, monkeypatch, route, query, limit
):
    _, headers = await team_context(
        client, api_user, f"kb-invalid-{route}-{abs(limit)}"
    )
    calls = []

    async def should_not_query(self, vector, namespace, top_k):
        calls.append((namespace, top_k))
        return {"matches": []}

    monkeypatch.setattr(
        KnowledgeBaseRAGService, "_pinecone_query", should_not_query
    )
    response = await client.post(
        f"/knowledge-base/{route}",
        json={"query": query, "limit": limit},
        headers=headers,
    )

    assert response.status_code == 422
    assert calls == []
