from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.middleware.auth_middleware import TeamContext
from app.models.team_member import MemberRole
from app.routers.billing import _validate_checkout_team
from app.routers.teams import _ensure_target_team
from app.services.teams_service import invite_member, update_member_role


def test_path_team_must_match_authenticated_team_context() -> None:
    context = TeamContext(team_id=uuid4(), role=MemberRole.admin)

    with pytest.raises(HTTPException) as exc_info:
        _ensure_target_team(uuid4(), context)

    assert exc_info.value.status_code == 400


def test_stripe_session_must_belong_to_active_team() -> None:
    context = TeamContext(team_id=uuid4(), role=MemberRole.admin)

    with pytest.raises(HTTPException) as exc_info:
        _validate_checkout_team(str(uuid4()), context)

    assert exc_info.value.status_code == 403


def test_valid_stripe_session_team_is_normalized() -> None:
    team_id = uuid4()
    context = TeamContext(team_id=team_id, role=MemberRole.admin)

    assert _validate_checkout_team(str(team_id), context) == team_id


@pytest.mark.asyncio
async def test_rep_cannot_change_member_roles() -> None:
    actor = SimpleNamespace(id=uuid4())
    membership = SimpleNamespace(role=MemberRole.rep)
    payload = SimpleNamespace(role=MemberRole.manager)

    with patch(
        "app.services.teams_service._get_membership",
        new=AsyncMock(return_value=membership),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_member_role(
                uuid4(),
                uuid4(),
                payload,
                actor,
                SimpleNamespace(),
            )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_invitation_targets_selected_team_only() -> None:
    team_id = uuid4()
    actor = SimpleNamespace(id=uuid4(), full_name="Enterprise Admin")
    membership = SimpleNamespace(role=MemberRole.admin)
    team = SimpleNamespace(
        id=team_id,
        name="Selected Team",
        invite_code="selected-team-code",
        created_at=datetime.now(timezone.utc),
        members=[],
    )
    payload = SimpleNamespace(email="new.member@example.com")

    get_membership = AsyncMock(return_value=membership)
    get_team = AsyncMock(return_value=team)
    send_email = AsyncMock()

    with (
        patch("app.services.teams_service._get_membership", new=get_membership),
        patch("app.services.teams_service._get_team_with_members", new=get_team),
        patch("app.services.teams_service._send_team_invite_email", new=send_email),
    ):
        response = await invite_member(
            team_id,
            payload,
            actor,
            SimpleNamespace(),
        )

    get_membership.assert_awaited_once_with(actor.id, team_id, ANY)
    get_team.assert_awaited_once_with(team_id, ANY)
    assert response.id == team_id
    assert response.invite_code == "selected-team-code"
