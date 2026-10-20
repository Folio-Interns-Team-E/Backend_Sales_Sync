from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.chat_service import ChatService


def rows(items):
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: items))


@pytest.mark.asyncio
async def test_email_context_is_bounded_and_scoped_to_team_and_lead():
    team_id, lead_id = uuid4(), uuid4()
    email = SimpleNamespace(
        status=SimpleNamespace(value="sent"),
        subject="A" * 250,
        body="B" * 900,
        sent_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
    )
    meeting = SimpleNamespace(
        date=date(2026, 10, 21),
        time=time(14, 0),
        timezone="Asia/Karachi",
        status="Scheduled",
        agenda="A" * 600,
        notes="N" * 600,
    )
    proposal = SimpleNamespace(
        status="Sent",
        outcome="Open",
        ai_metadata={"document_title": "Q4 proposal"},
        created_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[rows([email]), rows([meeting]), rows([proposal])])
    )

    context = await ChatService(db)._build_lead_sales_context(team_id, lead_id)

    assert context["recent_outreach"][0]["status"] == "sent"
    assert len(context["recent_outreach"][0]["subject"]) == 200
    assert len(context["recent_outreach"][0]["body"]) == 800
    assert len(context["meetings"][0]["agenda"]) == 500
    assert len(context["meetings"][0]["notes"]) == 500
    assert context["proposals"][0]["title"] == "Q4 proposal"

    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert "leads.team_id" in statements[0] and "emails.lead_id" in statements[0]
    assert "leads.team_id" in statements[1] and "meetings.lead_id" in statements[1]
    assert "proposals.team_id" in statements[2] and "proposals.lead_id" in statements[2]
    assert all("LIMIT" in statement for statement in statements)
