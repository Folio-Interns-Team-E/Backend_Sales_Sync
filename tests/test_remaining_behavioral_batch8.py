from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import proposals_service
from tests.test_core_resources import team_context


async def _create_proposal(client, headers, file_url: str):
    response = await client.post(
        "/proposals/",
        json={"file_url": file_url, "file_type": "pdf", "file_size": 256},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_prop_19_revision_creation_is_available_and_increments_atomically(
    client, api_user
):
    _, headers = await team_context(client, api_user, "prop-revision")
    proposal = await _create_proposal(
        client, headers, "https://example.invalid/revision-v1.pdf"
    )

    first = await client.post(
        f"/proposals/{proposal['id']}/revisions",
        json={
            "file_url": "https://example.invalid/revision-v2.pdf",
            "note": "Customer changes",
        },
        headers=headers,
    )
    second = await client.post(
        f"/proposals/{proposal['id']}/revisions",
        json={
            "file_url": "https://example.invalid/revision-v3.pdf",
            "note": "Final changes",
        },
        headers=headers,
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["version"] == 2
    assert second.json()["data"]["version"] == 3
    fetched = await client.get(f"/proposals/{proposal['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["version"] == 3


@pytest.mark.asyncio
async def test_prop_20_simultaneous_status_changes_are_controlled_and_consistent(
    client, api_user
):
    _, headers = await team_context(client, api_user, "prop-concurrent")
    proposal = await _create_proposal(
        client, headers, "https://example.invalid/concurrent.pdf"
    )

    async def update(status: str):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as concurrent_client:
            return await concurrent_client.patch(
                f"/proposals/{proposal['id']}/status",
                json={"status": status},
                headers=headers,
            )

    accepted, rejected = await asyncio.gather(
        update("Accepted"), update("Rejected")
    )
    assert accepted.status_code == rejected.status_code == 200

    fetched = await client.get(f"/proposals/{proposal['id']}", headers=headers)
    assert fetched.status_code == 200
    final_status = fetched.json()["data"]["status"]
    assert final_status in {"Accepted", "Rejected"}
    assert final_status in {
        accepted.json()["data"]["status"],
        rejected.json()["data"]["status"],
    }


@pytest.mark.asyncio
async def test_prop_21_presigned_url_does_not_expose_raw_bucket_location(
    client, api_user, monkeypatch
):
    _, owner_headers = await team_context(client, api_user, "prop-url-owner")
    raw_url = (
        "https://private-test-bucket.s3.us-east-1.amazonaws.com/"
        "proposals/owner/private-proposal.pdf"
    )
    proposal = await _create_proposal(client, owner_headers, raw_url)
    calls = []

    def fake_presign(s3_url: str, expiration: int = 3600):
        calls.append((s3_url, expiration))
        return (
            "https://signed.example.invalid/private-proposal.pdf"
            "?X-Amz-Expires=3600&X-Amz-Signature=redacted"
        )

    monkeypatch.setattr(proposals_service, "generate_presigned_url", fake_presign)
    owner = await client.get(f"/proposals/{proposal['id']}", headers=owner_headers)

    assert owner.status_code == 200
    data = owner.json()["data"]
    assert calls == [(raw_url, 3600)]
    assert data["presigned_url"].startswith("https://signed.example.invalid/")
    assert "amazonaws.com" not in owner.text
    assert raw_url not in owner.text


@pytest.mark.asyncio
async def test_prop_21_presigned_proposal_is_not_accessible_cross_team(
    client, api_user, monkeypatch
):
    _, owner_headers = await team_context(client, api_user, "prop-url-scope-owner")
    _, stranger_headers = await team_context(client, api_user, "prop-url-scope-stranger")
    raw_url = (
        "https://private-test-bucket.s3.us-east-1.amazonaws.com/"
        "proposals/owner/scoped-proposal.pdf"
    )
    proposal = await _create_proposal(client, owner_headers, raw_url)

    monkeypatch.setattr(
        proposals_service,
        "generate_presigned_url",
        lambda _url, expiration=3600: (
            "https://signed.example.invalid/scoped-proposal.pdf"
            "?X-Amz-Expires=3600&X-Amz-Signature=redacted"
        ),
    )
    stranger = await client.get(
        f"/proposals/{proposal['id']}", headers=stranger_headers
    )

    assert stranger.status_code in {403, 404}
