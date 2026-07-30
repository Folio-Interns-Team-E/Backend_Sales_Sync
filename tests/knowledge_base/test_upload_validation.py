from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.knowledge_base import KnowledgeAsset
from app.services import knowledge_base_service
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from tests.cross_feature.test_leads_meetings_proposals import team_context


def _install_successful_kb_boundaries(monkeypatch):
    stored = []

    def store(**kwargs):
        stored.append(kwargs)
        return {}

    async def index(self, asset, file_content):
        asset.status = "ready"
        asset.chunk_count = 1
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    monkeypatch.setattr(knowledge_base_service.s3_client, "put_object", store)
    monkeypatch.setattr(KnowledgeBaseRAGService, "index_asset", index)
    return stored


async def _upload(client, headers, filename, content, content_type, title="Asset"):
    return await client.post(
        "/knowledge-base/upload",
        data={"title": title},
        files={"file": (filename, content, content_type)},
        headers=headers,
    )


async def _asset_count(team_id: str) -> int:
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(func.count(KnowledgeAsset.id)).where(
                    KnowledgeAsset.team_id == UUID(team_id)
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("handbook.pdf", b"%PDF-1.4\nvalid test document", "application/pdf"),
        (
            "playbook.docx",
            b"PK\x03\x04minimal-docx-test",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("notes.txt", b"Plain searchable sales notes.", "text/plain"),
    ],
    ids=["pdf", "docx", "text"],
)
async def test_kb_01_supported_uploads_persist_and_finish_indexing(
    client, api_user, monkeypatch, filename, content, content_type
):
    _, headers = await team_context(client, api_user, f"kb-supported-{filename[-3:]}")
    stored = _install_successful_kb_boundaries(monkeypatch)

    response = await _upload(
        client, headers, filename, content, content_type, f"Uploaded {filename}"
    )

    assert response.status_code == 201, response.text
    assert len(stored) == 1
    assert stored[0]["Key"].startswith(
        f"knowledge-assets/{headers['X-Team-Id']}/"
    )
    data = response.json()["data"]
    assert data["status"] == "ready"
    assert data["chunk_count"] == 1
    assert data["file_size"] == len(content)
    assert await _asset_count(headers["X-Team-Id"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("empty.pdf", b"", "application/pdf"),
        ("corrupt.pdf", b"not a pdf", "application/pdf"),
        ("encrypted.pdf", b"%PDF-1.7 /Encrypt test", "application/pdf"),
        ("payload.exe", b"MZ executable", "application/x-msdownload"),
        ("spoofed.pdf", b"<script>alert(1)</script>", "application/pdf"),
        ("oversized.pdf", b"%PDF" + (b"x" * (25 * 1024 * 1024)), "application/pdf"),
    ],
    ids=["empty", "corrupt", "encrypted", "unsupported", "mime-spoof", "oversized"],
)
async def test_kb_02_invalid_uploads_are_rejected_before_storage(
    client, api_user, monkeypatch, filename, content, content_type
):
    _, headers = await team_context(client, api_user, f"kb-invalid-{filename[:5]}")
    stored = _install_successful_kb_boundaries(monkeypatch)

    response = await _upload(
        client, headers, filename, content, content_type, "Invalid document"
    )

    assert response.status_code in {400, 413, 415, 422}
    assert stored == []
    assert await _asset_count(headers["X-Team-Id"]) == 0


@pytest.mark.asyncio
async def test_kb_03_filenames_are_safe_tenant_scoped_and_collision_resistant(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "kb-filenames")
    stored = _install_successful_kb_boundaries(monkeypatch)
    inputs = ["../../secret.pdf", "客户资料 résumé.pdf", "duplicate.pdf", "duplicate.pdf"]

    responses = [
        await _upload(
            client,
            headers,
            filename,
            b"%PDF-1.4\nsafe content",
            "application/pdf",
            f"Document {index}",
        )
        for index, filename in enumerate(inputs)
    ]

    assert all(response.status_code == 201 for response in responses)
    keys = [call["Key"] for call in stored]
    assert len(keys) == len(set(keys)) == 4
    prefix = f"knowledge-assets/{headers['X-Team-Id']}/"
    assert all(key.startswith(prefix) for key in keys)
    basenames = [key.rsplit("/", 1)[-1] for key in keys]
    assert all("/" not in name and "\\" not in name and ".." not in name for name in basenames)
    assert await _asset_count(headers["X-Team-Id"]) == 4
