from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.middleware.auth_middleware import TeamContext
from app.models.team_member import MemberRole
from app.routers.teams import rotate_invite_code
from app.services.teams_service import rotate_team_invite_code


@pytest.mark.asyncio
async def test_admin_can_rotate_code_and_audit_change():
    team_id = uuid4()
    actor = SimpleNamespace(id=uuid4())
    team = SimpleNamespace(id=team_id, invite_code="old-code")
    db = SimpleNamespace(scalar=AsyncMock(return_value=team), commit=AsyncMock(), add=Mock())
    with (
        patch("app.services.teams_service._get_membership", new=AsyncMock(return_value=SimpleNamespace(role=MemberRole.admin))),
        patch("app.services.teams_service.record_audit_event") as audit,
    ):
        result = await rotate_team_invite_code(team_id, actor, db)
    assert result["invite_code"] != "old-code"
    assert len(result["invite_code"]) >= 20
    audit.assert_called_once_with(db, team_id, actor.id, "workspace.invite_code_rotated", "team", team_id)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_cannot_rotate_code():
    db = SimpleNamespace(scalar=AsyncMock(), commit=AsyncMock())
    with patch("app.services.teams_service._get_membership", new=AsyncMock(return_value=SimpleNamespace(role=MemberRole.manager))):
        with pytest.raises(HTTPException) as error:
            await rotate_team_invite_code(uuid4(), SimpleNamespace(id=uuid4()), db)
    assert error.value.status_code == 403
    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_key_cannot_rotate_invite_code():
    team_id = uuid4()
    actor = SimpleNamespace(id=uuid4(), _api_key_team_id=team_id)
    with patch("app.routers.teams.rotate_team_invite_code", new=AsyncMock()) as rotate:
        with pytest.raises(HTTPException) as error:
            await rotate_invite_code(team_id, actor, TeamContext(team_id, MemberRole.admin), SimpleNamespace())
    assert error.value.status_code == 403
    rotate.assert_not_awaited()
