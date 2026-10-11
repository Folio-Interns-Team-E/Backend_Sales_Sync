from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.team_member import MemberRole
from app.services.teams_service import remove_member, update_member_role


def team_response(team_id):
    return SimpleNamespace(id=team_id, name="Sales", invite_code="code", created_at=datetime.now(timezone.utc), members=[])


@pytest.mark.asyncio
async def test_role_change_and_audit_commit_together():
    team_id, actor_id, target_id = uuid4(), uuid4(), uuid4()
    actor = SimpleNamespace(id=actor_id)
    target = SimpleNamespace(role=MemberRole.rep)
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    with (
        patch("app.services.teams_service._get_membership", new=AsyncMock(side_effect=[SimpleNamespace(role=MemberRole.admin), target])),
        patch("app.services.teams_service._get_team_with_members", new=AsyncMock(return_value=team_response(team_id))),
    ):
        await update_member_role(team_id, target_id, SimpleNamespace(role=MemberRole.manager), actor, db)
    assert target.role == MemberRole.manager
    event = db.add.call_args.args[0]
    assert (event.action, event.team_id, event.actor_user_id, event.target_id) == (
        "workspace.member_role_changed", team_id, actor_id, str(target_id)
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_cannot_remove_admin_or_peer():
    for target_role in (MemberRole.admin, MemberRole.manager):
        db = SimpleNamespace(delete=AsyncMock(), add=Mock(), commit=AsyncMock())
        with patch("app.services.teams_service._get_membership", new=AsyncMock(side_effect=[SimpleNamespace(role=MemberRole.manager), SimpleNamespace(role=target_role)])):
            with pytest.raises(HTTPException) as error:
                await remove_member(uuid4(), uuid4(), SimpleNamespace(id=uuid4()), db)
        assert error.value.status_code == 403
        db.delete.assert_not_awaited()
        db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_removal_writes_audit_event():
    team_id, actor_id, target_id = uuid4(), uuid4(), uuid4()
    db = SimpleNamespace(delete=AsyncMock(), add=Mock(), commit=AsyncMock())
    with (
        patch("app.services.teams_service._get_membership", new=AsyncMock(side_effect=[SimpleNamespace(role=MemberRole.admin), SimpleNamespace(role=MemberRole.manager)])),
        patch("app.services.teams_service._get_team_with_members", new=AsyncMock(return_value=team_response(team_id))),
    ):
        await remove_member(team_id, target_id, SimpleNamespace(id=actor_id), db)
    event = db.add.call_args.args[0]
    assert (event.action, event.target_id) == ("workspace.member_removed", str(target_id))
    db.commit.assert_awaited_once()
