from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from app.core.security import create_access_token, decode_access_token, session_claims, session_matches_user
from app.models.security_event import SecurityAction
from app.routers.auth import logout_all


def test_session_version_invalidates_old_access_tokens():
    user = SimpleNamespace(id=uuid4(), hashed_password="hashed", session_version=0)
    token = create_access_token(session_claims(user))
    payload = decode_access_token(token)
    assert session_matches_user(payload, user)
    user.session_version = 1
    assert not session_matches_user(payload, user)


def test_existing_tokens_stay_valid_until_revocation():
    user = SimpleNamespace(id=uuid4(), hashed_password="hashed", session_version=0)
    old_claims = {key: value for key, value in session_claims(user).items() if key != "sv"}
    assert session_matches_user(old_claims, user)
    user.session_version = 1
    assert not session_matches_user(old_claims, user)


async def test_logout_all_updates_version_and_records_event_atomically():
    user = SimpleNamespace(id=uuid4())
    db = SimpleNamespace(execute=AsyncMock(), add=Mock(), commit=AsyncMock())
    response = await logout_all(Response(), user, db, authorization="Bearer token")
    assert response.status_code == 204
    assert "refresh_token=" in response.headers["set-cookie"]
    assert response.headers["Cache-Control"] == "no-store"
    assert db.execute.await_count == 1
    assert db.add.call_args.args[0].action == SecurityAction.logout_all
    db.commit.assert_awaited_once()


async def test_logout_all_rejects_api_key_only_authentication():
    db = SimpleNamespace(execute=AsyncMock(), add=Mock(), commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await logout_all(Response(), SimpleNamespace(id=uuid4()), db, authorization=None)
    assert error.value.status_code == 403
    db.execute.assert_not_awaited()
