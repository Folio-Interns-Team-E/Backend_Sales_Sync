from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_icp_chat_asks_drafts_and_waits_for_confirmation():
    user_id, team_id, chat_id = uuid4(), uuid4(), uuid4()
    team = SimpleNamespace(id=team_id, icp="Existing ICP")
    saved_messages = []
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    db.add = saved_messages.append

    async def execute(_statement):
        if execute.calls % 2 == 0:
            result = SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(full_name="User", email="user@example.com"))
        else:
            result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(reversed(saved_messages[-5:]))))
        execute.calls += 1
        return result

    execute.calls = 0
    db.execute = execute
    service = ChatService(db)
    service._get_team = AsyncMock(return_value=team)
    service._get_chat = AsyncMock(return_value=SimpleNamespace(id=chat_id))
    draft = "Firmographics:\n    Industries:\n    - Restaurants\n    Geography:\n    - Karachi\nBuyer_Personas:\n    - Restaurant owners\nPain_Points:\n    - Manual reservations\nValue_Proposition:\n    - Reservation automation"

    with patch("app.services.chat_service.SupervisorAgent") as supervisor, patch("app.services.chat_service.ICPAgent") as agent:
        supervisor.return_value.extract_action = AsyncMock(return_value={"action": "UPDATE_ICP"})
        agent.return_value.refine_icp = AsyncMock(return_value=draft)

        first = await service.send_message(user_id, team_id, chat_id, "Update my ICP: restaurant owners")
        assert "countries or cities" in first
        assert team.icp == "Existing ICP"

        second = await service.send_message(user_id, team_id, chat_id, "Karachi independent restaurants with 10-50 employees; owners struggle with reservations; we sell booking automation.")
        assert "Nothing has been saved yet" in second
        assert draft in second
        assert team.icp == "Existing ICP"

        third = await service.send_message(user_id, team_id, chat_id, "yes, save it")
        assert "now active" in third
        assert team.icp == draft


@pytest.mark.asyncio
async def test_meeting_chat_waits_for_explicit_confirmation_before_execution():
    user_id, team_id, chat_id, lead_id = uuid4(), uuid4(), uuid4(), uuid4()
    team = SimpleNamespace(id=team_id, icp="Existing ICP")
    saved_messages = []
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    db.add = saved_messages.append

    async def execute(_statement):
        if execute.calls % 2 == 0:
            result = SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(
                    full_name="User",
                    email="user@example.com",
                )
            )
        else:
            result = SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: list(reversed(saved_messages[-5:])))
            )
        execute.calls += 1
        return result

    execute.calls = 0
    db.execute = execute
    service = ChatService(db)
    service._get_team = AsyncMock(return_value=team)
    service._get_chat = AsyncMock(return_value=SimpleNamespace(id=chat_id))
    pending = {
        "type": "meeting",
        "decision": "CREATE",
        "lead_id": str(lead_id),
        "start_time": "2026-10-21T14:00:00",
        "timezone": "Asia/Karachi",
        "target_cancel_time": None,
    }

    with patch("app.services.chat_service.SupervisorAgent") as supervisor, patch(
        "app.services.chat_service.MeetingAgent"
    ) as meeting_agent:
        supervisor.return_value.extract_action = AsyncMock(
            return_value={"action": "MEETING_OPERATION", "parameters": {}}
        )
        meeting_agent.return_value.prepare = AsyncMock(
            return_value=(pending, "Please confirm this meeting")
        )
        meeting_agent.return_value.execute_prepared = AsyncMock(return_value="Meeting scheduled")

        first = await service.send_message(
            user_id,
            team_id,
            chat_id,
            "Schedule a meeting with Ada tomorrow at 2 PM",
        )
        assert first == "Please confirm this meeting"
        meeting_agent.return_value.execute_prepared.assert_not_awaited()

        second = await service.send_message(user_id, team_id, chat_id, "confirm")
        assert second == "Meeting scheduled"
        meeting_agent.return_value.execute_prepared.assert_awaited_once_with(
            pending,
            team_id,
            user_id,
        )


@pytest.mark.asyncio
async def test_intent_failure_is_saved_as_retryable_instead_of_crashing_handler():
    user_id, team_id, chat_id = uuid4(), uuid4(), uuid4()
    team = SimpleNamespace(id=team_id, icp="Existing ICP")
    saved_messages = []
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock(), rollback=AsyncMock())
    db.add = saved_messages.append

    async def execute(_statement):
        if execute.calls == 0:
            result = SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(
                    full_name="User",
                    email="user@example.com",
                )
            )
        else:
            result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        execute.calls += 1
        return result

    execute.calls = 0
    db.execute = execute
    service = ChatService(db)
    service._get_team = AsyncMock(return_value=team)
    service._get_chat = AsyncMock(return_value=SimpleNamespace(id=chat_id, chat_name="Existing"))

    with patch("app.services.chat_service.SupervisorAgent") as supervisor:
        supervisor.return_value.extract_action = AsyncMock(side_effect=RuntimeError("model unavailable"))
        response = await service.send_message(user_id, team_id, chat_id, "Draft an email")

    assert "encountered an error" in response
    assert saved_messages[-1].metadata_log == {
        "assistant_error": {
            "code": "assistant_processing_failed",
            "retryable": True,
        }
    }


@pytest.mark.asyncio
async def test_proposal_generation_waits_for_explicit_confirmation():
    user_id, team_id, chat_id = uuid4(), uuid4(), uuid4()
    team = SimpleNamespace(id=team_id, icp="Existing ICP")
    saved_messages = []
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock(), rollback=AsyncMock())
    db.add = saved_messages.append

    async def execute(_statement):
        if execute.calls == 0:
            result = SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(
                    full_name="User",
                    email="user@example.com",
                )
            )
        else:
            result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        execute.calls += 1
        return result

    execute.calls = 0
    db.execute = execute
    service = ChatService(db)
    service._get_team = AsyncMock(return_value=team)
    service._get_chat = AsyncMock(return_value=SimpleNamespace(id=chat_id, chat_name="Existing"))

    with patch("app.services.chat_service.SupervisorAgent") as supervisor, patch(
        "app.ai.proposal_agent.ProposalAgent"
    ) as proposal_agent:
        supervisor.return_value.extract_action = AsyncMock(
            return_value={
                "action": "GENERATE_PROPOSAL",
                "parameters": {"keywords": ["Acme"]},
            }
        )
        response = await service.send_message(
            user_id,
            team_id,
            chat_id,
            "Generate a proposal for Acme",
        )

    assert "Please confirm" in response
    assert "monthly proposal allowance" in response
    assert saved_messages[-1].metadata_log == {
        "pending_action": {
            "type": "proposal",
            "request": "Generate a proposal for Acme",
            "parameters": {"keywords": ["Acme"]},
        }
    }
    proposal_agent.assert_not_called()


@pytest.mark.asyncio
async def test_confirmed_proposal_uses_original_request_and_returns_record_action():
    user_id, team_id, chat_id = uuid4(), uuid4(), uuid4()
    team = SimpleNamespace(id=team_id, icp="Existing ICP")
    pending = {
        "type": "proposal",
        "request": "Generate a proposal for Acme",
        "parameters": {"keywords": ["Acme"]},
    }
    previous_ai = SimpleNamespace(
        sent_by="ai",
        content="Please confirm",
        created_at=None,
        metadata_log={"pending_action": pending},
    )
    saved_messages = []
    db = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
        is_active=True,
    )
    db.add = saved_messages.append

    async def execute(_statement):
        responses = [
            SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(
                    full_name="User",
                    email="user@example.com",
                )
            ),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [previous_ai])),
            SimpleNamespace(scalar_one_or_none=lambda: None),
        ]
        response = responses[min(execute.calls, len(responses) - 1)]
        execute.calls += 1
        return response

    execute.calls = 0
    db.execute = execute
    service = ChatService(db)
    service._get_team = AsyncMock(return_value=team)
    service._get_chat = AsyncMock(return_value=SimpleNamespace(id=chat_id, chat_name="Existing"))
    service.search_current_leads_by_name = AsyncMock(return_value=[])

    with patch("app.services.chat_service.SupervisorAgent"), patch(
        "app.services.chat_service.enforce_limit", new=AsyncMock()
    ), patch("app.ai.proposal_agent.ProposalAgent") as proposal_agent, patch(
        "app.core.s3.upload_to_s3", new=AsyncMock(return_value="s3://proposal")
    ), patch("app.services.chat_service.ProposalEvaluatorAgent") as evaluator:
        proposal_agent.return_value.run = AsyncMock(
            return_value=(
                "Acme_Proposal.docx",
                BytesIO(b"proposal"),
                {"document_title": "Acme Proposal"},
                {},
            )
        )
        evaluator.return_value.evaluate_proposal = AsyncMock(
            return_value={"passed": True, "overall_score": 9}
        )

        response = await service.send_message(user_id, team_id, chat_id, "confirm")

    assert "has been generated and saved as a draft" in response
    proposal_agent.return_value.run.assert_awaited_once()
    assert proposal_agent.return_value.run.await_args.kwargs["user_prompt"] == pending["request"]
    assert saved_messages[-1].metadata_log["action_result"]["type"] == "proposal_created"
