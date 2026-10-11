from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.team_member import MemberRole
from app.services.teams_service import invite_member, join_existing_team, rotate_team_invite_code


@pytest.mark.asyncio
async def test_expired_code_cannot_be_redeemed():
    team = SimpleNamespace(id=uuid4(), invite_code_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: team)), add=Mock(), commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await join_existing_team(SimpleNamespace(invite_code="expired"), SimpleNamespace(id=uuid4()), db)
    assert error.value.status_code == 410
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_expired_code_is_not_emailed():
    team = SimpleNamespace(id=uuid4(), invite_code="expired", invite_code_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    with (
        patch("app.services.teams_service._get_membership", new=AsyncMock(return_value=SimpleNamespace(role=MemberRole.admin))),
        patch("app.services.teams_service._get_team_with_members", new=AsyncMock(return_value=team)),
        patch("app.services.teams_service._send_team_invite_email", new=AsyncMock()) as send,
    ):
        with pytest.raises(HTTPException) as error:
            await invite_member(team.id, SimpleNamespace(email="someone@example.com"), SimpleNamespace(id=uuid4()), SimpleNamespace())
    assert error.value.status_code == 409
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_rotation_renews_code_for_thirty_days():
    team = SimpleNamespace(id=uuid4(), invite_code="expired", invite_code_expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    db = SimpleNamespace(scalar=AsyncMock(return_value=team), add=Mock(), commit=AsyncMock())
    with patch("app.services.teams_service._get_membership", new=AsyncMock(return_value=SimpleNamespace(role=MemberRole.admin))):
        result = await rotate_team_invite_code(team.id, SimpleNamespace(id=uuid4()), db)
    assert result["invite_code"] != "expired"
    remaining = result["invite_code_expires_at"] - datetime.now(timezone.utc)
    assert timedelta(days=29) < remaining <= timedelta(days=30)
