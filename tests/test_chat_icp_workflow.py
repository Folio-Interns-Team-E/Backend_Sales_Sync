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
