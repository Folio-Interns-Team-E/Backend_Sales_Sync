import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pyotp

from app.schemas.auth import LoginRequest
from app.services import auth_service, mfa_service


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)
        return 1


def result(value):
    return SimpleNamespace(scalar_one_or_none=lambda: value)


def user(**overrides):
    values = {
        "id": uuid4(),
        "email": "person@example.com",
        "full_name": "Person",
        "email_verified": True,
        "hashed_password": "hash",
        "session_version": 0,
        "mfa_enabled": True,
        "mfa_secret_encrypted": "encrypted-secret",
        "mfa_recovery_code_hashes": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_recovery_codes_are_unique_and_only_digests_are_stored():
    codes = mfa_service.generate_recovery_codes()
    digests = [mfa_service._recovery_digest(code) for code in codes]

    assert len(codes) == mfa_service.RECOVERY_CODE_COUNT
    assert len(set(codes)) == len(codes)
    assert all(len(code) == 14 and code.count("-") == 2 for code in codes)
    assert all(code not in digests for code in codes)


def test_recovery_code_is_single_use():
    code = "ABCD-EFGH-JKLM"
    account = user(mfa_recovery_code_hashes=json.dumps([mfa_service._recovery_digest(code)]))
    with patch.object(mfa_service, "_valid_totp", return_value=False):
        assert mfa_service.verify_user_code(account, "abcd-efgh-jklm")
        assert json.loads(account.mfa_recovery_code_hashes) == []
        assert not mfa_service.verify_user_code(account, code)


async def test_password_login_requires_mfa_before_tokens_are_issued():
    account = user()
    db = SimpleNamespace(execute=AsyncMock(return_value=result(account)))
    redis = FakeRedis()
    with (
        patch.object(auth_service, "get_redis", return_value=redis),
        patch.object(auth_service, "verify_password", return_value=True),
        patch.object(auth_service, "issue_login_challenge", return_value="mfa-ticket") as issue,
    ):
        response, refresh_token = await auth_service.login_user(
            LoginRequest(email=account.email, password="valid-password"), db
        )

    assert response.needs_mfa is True
    assert response.mfa_ticket == "mfa-ticket"
    assert response.access_token is None
    assert refresh_token is None
    issue.assert_called_once_with(account.id)


async def test_valid_totp_consumes_login_ticket_and_issues_session():
    account = user()
    secret = pyotp.random_base32()
    ticket = "secure-ticket"
    redis = FakeRedis()
    redis.values[mfa_service._ticket_key(ticket)] = str(account.id)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result(account)),
        add=Mock(),
        commit=AsyncMock(),
    )
    with (
        patch.object(mfa_service, "get_redis", return_value=redis),
        patch.object(mfa_service, "decrypt_key", return_value=secret),
    ):
        response, refresh_token = await mfa_service.complete_login(ticket, pyotp.TOTP(secret).now(), db)

    assert response.access_token
    assert refresh_token
    assert redis.get(mfa_service._ticket_key(ticket)) is None
    assert db.add.call_args.args[0].action.value == "mfa_login"
    db.commit.assert_awaited_once()
