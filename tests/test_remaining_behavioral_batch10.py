from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.knowledge_base import KnowledgeAsset, KnowledgeAssetChunk
from app.services import knowledge_base_service
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from tests.test_core_resources import team_context


async def _upload(client, headers, *, tags=None):
    data = {
        "title": "Sales handbook",
        "description": "Current positioning and pricing",
    }
    if tags is not None:
        data["tags"] = tags
    return await client.post(
        "/knowledge-base/upload",
        data=data,
        files={"file": ("handbook.pdf", b"%PDF-1.4\nbehavioral fixture", "application/pdf")},
        headers=headers,
    )


def _mock_storage(monkeypatch):
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
    return puts, deletes


async def _assets(team_id: str):
    async with SessionLocal() as db:
        result = await db.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.team_id == UUID(team_id))
            .order_by(KnowledgeAsset.created_at)
        )
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_kb_04_upload_metadata_and_tags_normalize_and_round_trip(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-metadata")
    _mock_storage(monkeypatch)

    async def indexed(self, asset, _content):
        asset.status = "ready"
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    monkeypatch.setattr(KnowledgeBaseRAGService, "index_asset", indexed)
    response = await _upload(client, headers, tags=" sales, pricing , ,sales, enterprise ")

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["title"] == "Sales handbook"
    assert data["description"] == "Current positioning and pricing"
    assert data["tags"] == ["sales", "pricing", "enterprise"]
    fetched = await client.get(f"/knowledge-base/{data['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["tags"] == data["tags"]


@pytest.mark.asyncio
async def test_kb_05_s3_failure_is_controlled_and_leaves_no_asset(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-s3-failure")

    def unavailable(**_kwargs):
        raise RuntimeError("private storage diagnostic")

    monkeypatch.setattr(knowledge_base_service.s3_client, "put_object", unavailable)
    response = await _upload(client, headers)

    assert response.status_code in {500, 502, 503, 504}
    assert "private storage diagnostic" not in response.text
    assert await _assets(headers["X-Team-Id"]) == []


@pytest.mark.asyncio
async def test_kb_05_extractor_failure_marks_failed_and_removes_stored_object(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-extract-failure")
    puts, deletes = _mock_storage(monkeypatch)

    async def extraction_failed(self, asset, _content):
        asset.status = "failed"
        asset.processing_error = "Document could not be parsed"
        await self.db.commit()
        await self.db.refresh(asset)
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Document could not be parsed")

    monkeypatch.setattr(KnowledgeBaseRAGService, "index_asset", extraction_failed)
    response = await _upload(client, headers)

    assert response.status_code == 400
    rows = await _assets(headers["X-Team-Id"])
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].processing_error
    assert len(puts) == len(deletes) == 1


@pytest.mark.asyncio
async def test_kb_05_vector_failure_does_not_leave_chunks_or_s3_orphan(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-vector-failure")
    puts, deletes = _mock_storage(monkeypatch)

    async def vector_failed(self, asset, _content):
        self.db.add(
            KnowledgeAssetChunk(
                team_id=asset.team_id,
                asset_id=asset.id,
                chunk_index=0,
                content="Unindexed content",
                pinecone_vector_id=f"{asset.id}:0",
                token_count=2,
            )
        )
        raise RuntimeError("private vector diagnostic")

    monkeypatch.setattr(KnowledgeBaseRAGService, "index_asset", vector_failed)
    response = await _upload(client, headers)

    assert response.status_code in {500, 502, 503, 504}
    assert "private vector diagnostic" not in response.text
    rows = await _assets(headers["X-Team-Id"])
    assert len(rows) == 1 and rows[0].status == "failed"
    async with SessionLocal() as db:
        chunks = (
            await db.execute(
                select(KnowledgeAssetChunk).where(
                    KnowledgeAssetChunk.asset_id == rows[0].id
                )
            )
        ).scalars().all()
    assert chunks == []
    assert len(puts) == len(deletes) == 1


async def _seed_asset(team_id: str, title: str, created_at: datetime):
    async with SessionLocal() as db:
        asset = KnowledgeAsset(
            team_id=UUID(team_id),
            title=title,
            tags=["seed"],
            file_url=(
                "https://private-test-bucket.s3.us-east-1.amazonaws.com/"
                f"knowledge-assets/{team_id}/{title}.pdf"
            ),
            source_url=None,
            file_type="pdf",
            file_size=100,
            status="ready",
            chunk_count=2,
            created_at=created_at,
        )
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        return str(asset.id)


@pytest.mark.asyncio
async def test_kb_06_list_get_are_tenant_safe_ordered_and_use_signed_urls(
    client, api_user, monkeypatch
):
    _, owner_headers = await team_context(client, api_user, "kb-list-owner")
    _, stranger_headers = await team_context(client, api_user, "kb-list-stranger")
    now = datetime.now(timezone.utc)
    older_id = await _seed_asset(owner_headers["X-Team-Id"], "Older", now - timedelta(days=1))
    newer_id = await _seed_asset(owner_headers["X-Team-Id"], "Newer", now)
    await _seed_asset(stranger_headers["X-Team-Id"], "Private", now + timedelta(days=1))
    signed = []

    def presign(url, expiration=3600):
        signed.append((url, expiration))
        return f"https://signed.example.invalid/{url.rsplit('/', 1)[-1]}?expires={expiration}"

    monkeypatch.setattr(knowledge_base_service, "generate_presigned_url", presign)
    listed = await client.get("/knowledge-base/", headers=owner_headers)
    fetched = await client.get(f"/knowledge-base/{older_id}", headers=owner_headers)

    assert listed.status_code == fetched.status_code == 200
    items = listed.json()["data"]
    assert [item["id"] for item in items] == [newer_id, older_id]
    assert all(item["status"] == "ready" and item["chunk_count"] == 2 for item in items)
    assert all(item["presigned_url"] for item in items)
    assert all("amazonaws.com" not in str(item) for item in items)
    assert fetched.json()["data"]["presigned_url"]
    assert "amazonaws.com" not in fetched.text
    assert len(signed) == 3
