from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from uuid import UUID

from app.database import SessionLocal
from app.models.team import Team
from app.services import chat_service
from tests.cross_feature.test_leads_meetings_proposals import create_lead, team_context


class DraftSupervisor:
    def __init__(self, db):
        self.db = db

    async def extract_action(self, message, icp):
        return {"action": "DRAFT_EMAIL", "parameters": {"keywords": ["Tone"]}}

    async def run(
        self, user_prompt, execution_result, team_id, messages_history, user_info
    ):
        return execution_result


@pytest.mark.asyncio
@pytest.mark.parametrize("tone", ["Professional", "Friendly", "Concise"])
async def test_mail_05_ai_draft_uses_lead_team_and_tone_context_and_is_stored(
    client, api_user, monkeypatch, tone
):
    _, headers = await team_context(client, api_user, f"mail-ai-{tone.lower()}")
    lead = await create_lead(client, headers, "Tone")
    team_id = headers["X-Team-Id"]
    async with SessionLocal() as db:
        team = (
            await db.execute(select(Team).where(Team.id == UUID(team_id)))
        ).scalar_one()
        team.icp = "Target B2B revenue teams that need pipeline automation"
        await db.commit()

    captured = {}

    class SuccessfulEmailAgent:
        async def generate_custom_email(
            self, lead_info, icp, message, revision_feedback=""
        ):
            captured.update(
                lead_info=lead_info,
                icp=icp,
                message=message,
                revision_feedback=revision_feedback,
            )
            return {
                "subject": f"{tone} pipeline idea",
                "body": (
                    f"A {tone.lower()} observation for {lead_info['name']}.\n\n"
                    f"Our pipeline automation fits {lead_info['company']}.\n\n"
                    "Would exploring this be useful?"
                ),
            }

        async def evaluate_email(self, email_content, lead_info, icp, message):
            return {"approved": True, "feedback": ""}

    monkeypatch.setattr(chat_service, "SupervisorAgent", DraftSupervisor)
    monkeypatch.setattr(chat_service, "EmailAgent", SuccessfulEmailAgent)
    prompt = f"Draft a {tone.lower()} email for Tone"
    response = await client.post("/chat/", json={"message": prompt}, headers=headers)
    history = await client.get(f"/emails/?lead_id={lead['id']}", headers=headers)

    assert response.status_code == 200, response.text
    assert captured["lead_info"]["name"] == lead["name"]
    assert captured["lead_info"]["email"] == lead["email"]
    assert captured["icp"] == "Target B2B revenue teams that need pipeline automation"
    assert tone.lower() in captured["message"].lower()
    drafts = history.json()["data"]
    assert len(drafts) == 1
    assert drafts[0]["status"] == "draft"
    assert drafts[0]["subject"] == f"{tone} pipeline idea"
    assert drafts[0]["body"].count("\n\n") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("AI provider timed out"),
        ValueError("malformed AI response"),
    ],
    ids=["timeout", "malformed"],
)
async def test_mail_06_ai_failure_is_controlled_and_does_not_destroy_existing_draft(
    client, api_user, monkeypatch, failure
):
    _, headers = await team_context(client, api_user, "mail-ai-failure")
    lead = await create_lead(client, headers, "Tone")
    existing = await client.post(
        "/emails/draft",
        json={
            "lead_id": lead["id"],
            "subject": "Recoverable subject",
            "body": "Recoverable body",
        },
        headers=headers,
    )
    assert existing.status_code == 201

    class FailedEmailAgent:
        async def generate_custom_email(self, *args, **kwargs):
            raise failure

    monkeypatch.setattr(chat_service, "SupervisorAgent", DraftSupervisor)
    monkeypatch.setattr(chat_service, "EmailAgent", FailedEmailAgent)
    response = await client.post(
        "/chat/",
        json={"message": "Draft a professional email for Tone"},
        headers=headers,
    )
    history = await client.get(f"/emails/?lead_id={lead['id']}", headers=headers)

    assert response.status_code in {400, 422, 502, 503, 504}
    assert "Traceback" not in response.text
    drafts = history.json()["data"]
    assert len(drafts) == 1
    assert drafts[0]["subject"] == "Recoverable subject"
    assert drafts[0]["body"] == "Recoverable body"
