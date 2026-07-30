from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models.email import Email
from app.models.lead import Lead
from app.models.proposal import Proposal
from app.models.team import Team
from app.models.team_member import TeamMember
from tests.test_core_resources import create_lead, team_context


@pytest.mark.asyncio
async def test_core_10_ambiguous_create_retry_is_idempotent_and_atomic(
    client, api_user
):
    _, headers = await team_context(client, api_user, "core-10")
    retry_key = f"core-10-{uuid4().hex}"
    email = f"{retry_key}@example.com"
    payload = {
        "name": "Ambiguous Retry",
        "email": email,
        "company": "Retry Co",
        "title": "Buyer",
        "source": "API retry",
    }
    request_headers = {**headers, "Idempotency-Key": retry_key}

    # Model a client that lost the first response after the server committed, then
    # safely repeated the same request with the same operation identifier.
    first = await client.post("/leads/", json=payload, headers=request_headers)
    retry = await client.post("/leads/", json=payload, headers=request_headers)
    listed = await client.get("/leads/", headers=headers)

    assert first.status_code == 201, first.text
    assert retry.status_code in {200, 201}, retry.text
    assert listed.status_code == 200, listed.text
    matching = [lead for lead in listed.json()["data"] if lead["email"] == email]
    assert len(matching) == 1
    assert retry.json()["data"]["id"] == first.json()["data"]["id"] == matching[0]["id"]

    async with SessionLocal() as db:
        persisted = await db.scalar(
            select(func.count()).select_from(Lead).where(Lead.email == email)
        )
    assert persisted == 1


@pytest.mark.asyncio
async def test_core_14_team_delete_cascades_dependents_without_deleting_user(
    client, api_user
):
    user, headers = await team_context(client, api_user, "core-14")
    team_id = UUID(headers["X-Team-Id"])
    lead = await create_lead(client, headers, "TeamCascade")
    draft = await client.post(
        "/emails/draft",
        json={"lead_id": lead["id"], "subject": "Cascade", "body": "Body"},
        headers=headers,
    )
    proposal = await client.post(
        "/proposals/",
        json={
            "lead_id": lead["id"],
            "file_url": "https://example.invalid/team-cascade.pdf",
        },
        headers=headers,
    )
    assert draft.status_code == proposal.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        deleted = await safe_client.delete(f"/teams/{team_id}", headers=headers)

    assert deleted.status_code == 200, deleted.text
    teams_after = await client.get("/teams/", headers=user["headers"])
    assert teams_after.status_code == 200
    assert all(team["id"] != str(team_id) for team in teams_after.json()["data"])

    async with SessionLocal() as db:
        assert await db.get(Team, team_id) is None
        assert await db.get(Lead, UUID(lead["id"])) is None
        assert await db.get(Email, UUID(draft.json()["data"]["id"])) is None
        assert await db.get(Proposal, UUID(proposal.json()["data"]["id"])) is None
        membership_count = await db.scalar(
            select(func.count())
            .select_from(TeamMember)
            .where(TeamMember.team_id == team_id)
        )
        assert membership_count == 0

    # Team deletion must remove the membership, not the account.
    auth_still_works = await client.get("/teams/", headers=user["headers"])
    assert auth_still_works.status_code == 200
