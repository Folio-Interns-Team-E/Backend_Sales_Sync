from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.team_member import MemberRole
from app.routers.leads import HunterKeyInput, configure_hunter, disconnect_hunter


@pytest.mark.asyncio
async def test_rep_can_configure_hunter_for_workspace():
    team_id = uuid4()
    team_ctx = SimpleNamespace(team_id=team_id, role=MemberRole.rep)
    db = AsyncMock()
    record = SimpleNamespace(monthly_limit=50, used_this_month=0)
    with patch("app.routers.leads.save_provider", new=AsyncMock(return_value=record)) as save:
        response = await configure_hunter(HunterKeyInput(api_key="test-key-123"), db, team_ctx)
    save.assert_awaited_once_with(db, team_id, "test-key-123", 50, "hunter")
    assert response.data.connected is True


@pytest.mark.asyncio
async def test_rep_can_disconnect_hunter_for_workspace():
    team_ctx = SimpleNamespace(team_id=uuid4(), role=MemberRole.rep)
    db = SimpleNamespace(delete=AsyncMock(), commit=AsyncMock())
    record = object()
    with patch("app.routers.leads.get_provider", new=AsyncMock(return_value=record)):
        await disconnect_hunter(db, team_ctx)
    db.delete.assert_awaited_once_with(record)
    db.commit.assert_awaited_once()
