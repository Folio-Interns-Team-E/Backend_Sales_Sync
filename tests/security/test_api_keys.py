import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.middleware.auth_middleware import get_current_user, get_team_context
from app.routers.api_keys import require_session_user


async def test_api_key_authentication_uses_hash_and_tracks_usage():
    raw_key = "ss_live_test-secret"
    team_id, user_id = uuid4(), uuid4()
    key = SimpleNamespace(created_by=user_id, team_id=team_id, last_used_at=None)
    user = SimpleNamespace(id=user_id, email_verified=True)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[key, user]), commit=AsyncMock())

    result = await get_current_user(credentials=None, x_api_key=raw_key, db=db)

    assert result is user
    assert result._api_key_team_id == team_id
    assert key.last_used_at is not None
    statement = db.scalar.call_args_list[0].args[0]
    assert hashlib.sha256(raw_key.encode()).hexdigest() in statement.compile().params.values()
    db.commit.assert_awaited_once()


async def test_invalid_api_key_is_rejected():
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await get_current_user(credentials=None, x_api_key="invalid", db=db)
    assert error.value.status_code == 401
    db.commit.assert_not_awaited()


async def test_api_key_cannot_switch_workspaces():
    user = SimpleNamespace(id=uuid4(), _api_key_team_id=uuid4())
    with pytest.raises(HTTPException) as error:
        await get_team_context(str(uuid4()), user, SimpleNamespace(execute=AsyncMock()))
    assert error.value.status_code == 403


async def test_api_key_infers_its_workspace_when_header_is_absent():
    team_id = uuid4()
    user = SimpleNamespace(id=uuid4(), _api_key_team_id=team_id)
    membership = SimpleNamespace(role=SimpleNamespace(value="admin"))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: membership)))
    context = await get_team_context(None, user, db)
    assert context.team_id == team_id


def test_api_keys_cannot_manage_other_credentials():
    with pytest.raises(HTTPException) as error:
        require_session_user(SimpleNamespace(_api_key_team_id=uuid4()))
    assert error.value.status_code == 403
