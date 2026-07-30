from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from uuid import UUID

from app.database import SessionLocal
from app.main import app
from app.models.proposal import ProposalTemplate
from app.services import proposals_service
from tests.cross_feature.test_leads_meetings_proposals import team_context


async def _safe_upload(headers, filename, content_type, content, template_name):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        return await safe_client.post(
            "/proposals/template/upload",
            data={"template_name": template_name},
            files={"file": (filename, content, content_type)},
            headers=headers,
        )


async def _template_count(team_id: str) -> int:
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(func.count(ProposalTemplate.id)).where(
                    ProposalTemplate.team_id == UUID(team_id)
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_prop_15_first_upload_and_replacement_persist_latest_template(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "prop-template")
    uploads = []

    async def stored(**kwargs):
        uploads.append(kwargs)
        return f"https://test-bucket.invalid/{kwargs['filename']}"

    monkeypatch.setattr(proposals_service, "s3_upload", stored)
    first = await _safe_upload(
        headers,
        "first.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"first-template",
        "First template",
    )
    replacement = await _safe_upload(
        headers,
        "replacement.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"replacement-template",
        "Replacement template",
    )

    assert first.status_code == replacement.status_code == 201
    assert len(uploads) == 2
    assert await _template_count(headers["X-Team-Id"]) == 1
    data = replacement.json()["data"]
    assert data["template_name"] == "Replacement template"
    assert data["file_url"].endswith("/replacement.docx")
    assert data["file_size"] == len(b"replacement-template")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("payload.exe", "application/x-msdownload", b"MZ executable"),
        ("../../escape.docx", "application/octet-stream", b"not a docx"),
        ("empty.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b""),
        ("spoofed.docx", "application/pdf", b"<script>alert(1)</script>"),
    ],
    ids=["executable", "path-traversal", "empty", "mime-spoof"],
)
async def test_prop_16_unsafe_template_uploads_are_rejected_before_storage(
    client, api_user, monkeypatch, filename, content_type, content
):
    _, headers = await team_context(client, api_user, f"prop-unsafe-{filename[-4:]}")
    storage_calls = []

    async def should_not_store(**kwargs):
        storage_calls.append(kwargs)
        return "https://test-bucket.invalid/unsafe"

    monkeypatch.setattr(proposals_service, "s3_upload", should_not_store)
    response = await _safe_upload(
        headers, filename, content_type, content, "Unsafe template"
    )

    assert response.status_code in {400, 413, 415, 422}
    assert storage_calls == []
    assert await _template_count(headers["X-Team-Id"]) == 0


@pytest.mark.asyncio
async def test_prop_17_storage_failure_returns_controlled_error_and_rolls_back(
    client, api_user, monkeypatch
):
    _, headers = await team_context(client, api_user, "prop-storage-failure")
    storage_calls = []

    async def unavailable(**kwargs):
        storage_calls.append(kwargs)
        raise RuntimeError("test storage unavailable")

    monkeypatch.setattr(proposals_service, "s3_upload", unavailable)
    response = await _safe_upload(
        headers,
        "valid.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"valid-template",
        "Valid template",
    )

    assert response.status_code in {502, 503, 504}
    assert len(storage_calls) == 1
    assert "test storage unavailable" not in response.text
    assert await _template_count(headers["X-Team-Id"]) == 0
