from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.knowledge_base import KnowledgeAsset, KnowledgeAssetChunk
from app.services import knowledge_base_service
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from tests.cross_feature.test_leads_meetings_proposals import team_context


async def _seed_asset(
    team_id: str,
    title: str,
    description: str,
    tags: list[str],
    *,
    created_at: datetime | None = None,
):
    async with SessionLocal() as db:
        asset = KnowledgeAsset(
            team_id=UUID(team_id),
            title=title,
            description=description,
            tags=tags,
            file_url=(
                "https://test-bucket.s3.us-east-1.amazonaws.com/"
                f"knowledge-assets/{team_id}/{title.replace(' ', '-')}.pdf"
            ),
            source_url="source-identity",
            file_type="pdf",
            file_size=321,
            status="ready",
            embedding_id="embedding-identity",
            chunk_count=1,
            created_at=created_at or datetime.now(timezone.utc),
        )
        db.add(asset)
        await db.flush()
        db.add(
            KnowledgeAssetChunk(
                team_id=UUID(team_id),
                asset_id=asset.id,
                chunk_index=0,
                content=f"Indexed content for {title}",
                pinecone_vector_id=f"{asset.id}:0",
                token_count=4,
            )
        )
        await db.commit()
        await db.refresh(asset)
        return str(asset.id)


async def _asset_exists(asset_id: str) -> bool:
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(KnowledgeAsset.id).where(
                    KnowledgeAsset.id == UUID(asset_id)
                )
            )
        ).scalar_one_or_none() is not None


async def _chunk_count(asset_id: str) -> int:
    async with SessionLocal() as db:
        return len(
            (
                await db.execute(
                    select(KnowledgeAssetChunk).where(
                        KnowledgeAssetChunk.asset_id == UUID(asset_id)
                    )
                )
            ).scalars().all()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_title"),
    [
        ("ENTERPRISE", "Enterprise Playbook"),
        ("healthcare", "Vertical Notes"),
        ("pricing", "Commercial Guide"),
        ("does-not-exist", None),
    ],
    ids=["title-case-insensitive", "description", "tag", "empty-state"],
)
async def test_kb_07_source_library_searches_title_description_and_tags(
    client, api_user, query, expected_title
):
    _, headers = await team_context(client, api_user, f"kb-library-{query[:4]}")
    now = datetime.now(timezone.utc)
    await _seed_asset(
        headers["X-Team-Id"],
        "Enterprise Playbook",
        "Large account motion",
        ["sales"],
        created_at=now,
    )
    await _seed_asset(
        headers["X-Team-Id"],
        "Vertical Notes",
        "Healthcare discovery questions",
        ["industry"],
        created_at=now - timedelta(seconds=1),
    )
    await _seed_asset(
        headers["X-Team-Id"],
        "Commercial Guide",
        "Packaging reference",
        ["pricing"],
        created_at=now - timedelta(seconds=2),
    )

    response = await client.get(
        "/knowledge-base/", params={"query": query}, headers=headers
    )

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["data"]]
    assert titles == ([] if expected_title is None else [expected_title])


@pytest.mark.asyncio
async def test_kb_08_patch_and_clear_metadata_preserves_file_and_vector_identity(
    client, api_user
):
    _, headers = await team_context(client, api_user, "kb-patch")
    asset_id = await _seed_asset(
        headers["X-Team-Id"],
        "Original",
        "Original description",
        ["old", "tags"],
    )
    before = await client.get(f"/knowledge-base/{asset_id}", headers=headers)
    changed = await client.patch(
        f"/knowledge-base/{asset_id}",
        json={
            "title": "Updated",
            "description": "Updated description",
            "tags": ["new"],
        },
        headers=headers,
    )
    cleared = await client.patch(
        f"/knowledge-base/{asset_id}",
        json={"description": "", "tags": []},
        headers=headers,
    )

    assert before.status_code == changed.status_code == cleared.status_code == 200
    original = before.json()["data"]
    updated = changed.json()["data"]
    empty = cleared.json()["data"]
    assert updated["title"] == "Updated"
    assert updated["description"] == "Updated description"
    assert updated["tags"] == ["new"]
    assert empty["title"] == "Updated"
    assert empty["description"] == ""
    assert empty["tags"] == []
    for field in ["file_url", "file_type", "file_size", "embedding_id", "chunk_count"]:
        assert updated[field] == empty[field] == original[field]
    assert await _chunk_count(asset_id) == 1


@pytest.mark.asyncio
async def test_kb_09_delete_removes_database_vectors_and_s3_object(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-delete")
    asset_id = await _seed_asset(
        headers["X-Team-Id"], "Delete Me", "Disposable", ["delete"]
    )
    s3_deletes, vector_deletes = [], []
    monkeypatch.setattr(
        knowledge_base_service.s3_client,
        "delete_object",
        lambda **kwargs: s3_deletes.append(kwargs) or {},
    )

    async def delete_vectors(self, asset):
        vector_deletes.append((str(asset.team_id), str(asset.id)))

    monkeypatch.setattr(KnowledgeBaseRAGService, "delete_asset_index", delete_vectors)
    response = await client.delete(
        f"/knowledge-base/{asset_id}", headers=headers
    )

    assert response.status_code == 200
    assert len(s3_deletes) == len(vector_deletes) == 1
    assert not await _asset_exists(asset_id)
    assert await _chunk_count(asset_id) == 0


@pytest.mark.asyncio
async def test_kb_09_delete_dependency_failure_does_not_report_false_success(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-delete-failure")
    asset_id = await _seed_asset(
        headers["X-Team-Id"], "Retain Me", "Cleanup failure", ["retain"]
    )

    def s3_failure(**_kwargs):
        raise RuntimeError("redacted delete failure")

    async def vector_failure(self, asset):
        raise RuntimeError("redacted vector failure")

    monkeypatch.setattr(
        knowledge_base_service.s3_client, "delete_object", s3_failure
    )
    monkeypatch.setattr(
        KnowledgeBaseRAGService, "delete_asset_index", vector_failure
    )
    response = await client.delete(
        f"/knowledge-base/{asset_id}", headers=headers
    )

    assert response.status_code in {409, 500, 502, 503, 504}
    assert await _asset_exists(asset_id)
    assert await _chunk_count(asset_id) == 1
