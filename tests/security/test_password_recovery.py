import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from app.core.security import session_claims, session_matches_user, verify_password
from app.schemas.auth import PasswordResetConfirm
from app.services.password_recovery import confirm_reset, request_reset, RESET_TTL
from app.schemas.auth import RegisterRequest
from app.services.auth_service import register_user, _otp_digest


def user():
    return SimpleNamespace(id=uuid4(), email="person@example.com", hashed_password="old-hash")


def database(account):
    return SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: account)), commit=AsyncMock())


async def test_recovery_stores_digest_and_expires_without_disclosing_account():
    account = user()
    redis = Mock()
    redis.incr.return_value = 1
    tasks = BackgroundTasks()
    with patch("app.services.password_recovery.get_redis", return_value=redis):
        assert await request_reset(account.email, "127.0.0.1", tasks, database(account)) is None
    token = tasks.tasks[0].args[1]
    key, stored = redis.set.call_args.args
    assert len(token) == 43
    assert token not in key and token not in stored
    assert redis.set.call_args.kwargs["ex"] == RESET_TTL
    tasks = BackgroundTasks()
    with patch("app.services.password_recovery.get_redis", return_value=redis):
        assert await request_reset("missing@example.com", "127.0.0.1", tasks, database(None)) is None
    assert not tasks.tasks


async def test_reset_invalidates_old_sessions_and_cannot_be_replayed():
    account = user()
    old_claims = session_claims(account)
    redis = Mock()
    redis.getdel.side_effect = [json.dumps(old_claims), None]
    db = database(account)
    with patch("app.services.password_recovery.get_redis", return_value=redis):
        await confirm_reset("x" * 43, "new-password-123", db)
        assert verify_password("new-password-123", account.hashed_password)
        assert not session_matches_user(old_claims, account)
        assert session_matches_user(session_claims(account), account)
        with pytest.raises(HTTPException) as error:
            await confirm_reset("x" * 43, "another-password", db)
        assert error.value.status_code == 400
    db.commit.assert_awaited_once()


async def test_reset_rejects_credential_issued_before_password_change():
    account = user()
    stored = json.dumps(session_claims(account))
    account.hashed_password = "changed-hash"
    redis = Mock(getdel=Mock(return_value=stored))
    db = database(account)
    with patch("app.services.password_recovery.get_redis", return_value=redis):
        with pytest.raises(HTTPException):
            await confirm_reset("x" * 43, "new-password", db)
    db.commit.assert_not_awaited()


async def test_recovery_fails_when_redis_unavailable():
    with patch("app.services.password_recovery.get_redis", return_value=None):
        with pytest.raises(HTTPException) as error:
            await confirm_reset("x" * 43, "new-password", database(user()))
    assert error.value.status_code == 503


async def test_recovery_limits_requests_before_account_lookup():
    redis = Mock(incr=Mock(return_value=11))
    db = database(user())
    with patch("app.services.password_recovery.get_redis", return_value=redis):
        with pytest.raises(HTTPException) as error:
            await request_reset("person@example.com", "127.0.0.1", BackgroundTasks(), db)
    assert error.value.status_code == 429
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("password", ["short", "é" * 40])
def test_reset_rejects_invalid_passwords(password):
    with pytest.raises(ValidationError):
        PasswordResetConfirm(token="x" * 43, password=password)


async def test_registration_stores_verifiable_hashed_otp():
    db = database(None)
    db.add = Mock(side_effect=lambda account: setattr(account, "id", uuid4()))
    db.refresh = AsyncMock()
    redis = Mock()
    with (
        patch("app.services.auth_service.get_redis", return_value=redis),
        patch("app.services.auth_service.send_otp_email", new_callable=AsyncMock) as send,
    ):
        await register_user(RegisterRequest(full_name="Test Person", email="person@example.com", password="password-123"), db)
    code = send.call_args.args[1]
    assert redis.set.call_args.args[1] == _otp_digest(code)
    assert redis.set.call_args.args[1] != code
