from __future__ import annotations

import asyncio

import pytest

from tests.cross_feature.test_leads_meetings_proposals import create_lead, team_context


async def _proposal(client, headers, lead_id, suffix):
    response = await client.post(
        "/proposals/",
        json={
            "lead_id": lead_id,
            "file_url": f"https://example.invalid/{suffix}.pdf",
            "file_type": "pdf",
            "file_size": 100,
            "ai_metadata": {"source": "initial"},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_prop_05_supported_patch_fields_persist_and_omitted_fields_survive(
    client, api_user
):
    _, headers = await team_context(client, api_user, "prop-update")
    first_lead = await create_lead(client, headers, "ProposalFirst")
    second_lead = await create_lead(client, headers, "ProposalSecond")
    item = await _proposal(client, headers, first_lead["id"], "initial")

    updated = await client.patch(
        f"/proposals/{item['id']}",
        json={
            "lead_id": second_lead["id"],
            "file_url": "https://example.invalid/replaced.docx",
            "file_type": "docx",
            "file_size": 2048,
            "ai_metadata": {"source": "revision", "quality": 9},
        },
        headers=headers,
    )
    partial = await client.patch(
        f"/proposals/{item['id']}",
        json={"file_size": 4096},
        headers=headers,
    )

    assert updated.status_code == partial.status_code == 200
    data = partial.json()["data"]
    assert data["lead_id"] == second_lead["id"]
    assert data["file_url"] == "https://example.invalid/replaced.docx"
    assert data["file_type"] == "docx"
    assert data["file_size"] == 4096
    assert data["ai_metadata"] == {"source": "revision", "quality": 9}
    assert data["version"] == 1


@pytest.mark.asyncio
async def test_prop_06_frontend_patch_fields_are_not_silently_discarded(
    client, api_user
):
    _, headers = await team_context(client, api_user, "prop-contract")
    lead = await create_lead(client, headers, "ProposalContract")
    item = await _proposal(client, headers, lead["id"], "contract")
    response = await client.patch(
        f"/proposals/{item['id']}",
        json={
            "title": "Enterprise rollout",
            "summary": "A supported customer-facing summary",
            "value": 25000,
            "status": "Sent",
            "outcome": "Won",
        },
        headers=headers,
    )
    assert response.status_code == 422
    for field in ["title", "summary", "value", "status", "outcome"]:
        assert field in response.text


@pytest.mark.asyncio
async def test_prop_19_sequential_revisions_increment_and_preserve_history(
    client, api_user
):
    _, headers = await team_context(client, api_user, "prop-revisions")
    lead = await create_lead(client, headers, "ProposalRevision")
    item = await _proposal(client, headers, lead["id"], "revision-base")
    first = await client.post(
        f"/proposals/{item['id']}/revisions",
        json={"title": "Revision one", "summary": "First change", "note": "Editor A"},
        headers=headers,
    )
    second = await client.post(
        f"/proposals/{item['id']}/revisions",
        json={"title": "Revision two", "summary": "Second change", "note": "Editor B"},
        headers=headers,
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["version"] == 2
    assert second.json()["data"]["version"] == 3
    fetched = await client.get(f"/proposals/{item['id']}", headers=headers)
    assert fetched.json()["data"]["version"] == 3


@pytest.mark.asyncio
async def test_prop_20_concurrent_revisions_receive_unique_atomic_versions(
    client, api_user
):
    _, headers = await team_context(client, api_user, "prop-concurrent")
    lead = await create_lead(client, headers, "ProposalConcurrent")
    item = await _proposal(client, headers, lead["id"], "concurrent-base")
    first, second = await asyncio.gather(
        client.post(
            f"/proposals/{item['id']}/revisions",
            json={"title": "Concurrent A", "summary": "A", "note": "Editor A"},
            headers=headers,
        ),
        client.post(
            f"/proposals/{item['id']}/revisions",
            json={"title": "Concurrent B", "summary": "B", "note": "Editor B"},
            headers=headers,
        ),
    )
    assert first.status_code == second.status_code == 201
    versions = {
        first.json()["data"]["version"],
        second.json()["data"]["version"],
    }
    assert versions == {2, 3}
