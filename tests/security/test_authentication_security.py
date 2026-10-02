from fastapi import Response

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.routers.auth import logout
from app.services.auth_service import (
    LOGIN_ATTEMPT_WINDOW_SECONDS,
    _login_attempt_key,
    _otp_digest,
    _record_failed_login,
    generate_six_digit_otp,
)


def test_access_and_refresh_tokens_are_not_interchangeable() -> None:
    access_token = create_access_token({"sub": "user-1"})
    refresh_token = create_refresh_token({"sub": "user-1"})

    assert decode_access_token(access_token)["type"] == "access"
    assert decode_refresh_token(refresh_token)["type"] == "refresh"
    assert decode_refresh_token(access_token) is None
    assert decode_access_token(refresh_token) is None


def test_access_token_contains_enterprise_session_claims() -> None:
    payload = decode_access_token(create_access_token({"sub": "user-1"}))

    assert payload is not None
    assert payload["jti"]
    assert payload["iss"]
    assert payload["aud"]
    assert payload["exp"] - payload["iat"] <= 15 * 60


def test_otp_is_six_digit_cryptographically_generated_value() -> None:
    generated = {generate_six_digit_otp() for _ in range(20)}

    assert len(generated) > 1
    assert all(len(otp) == 6 and otp.isdigit() for otp in generated)


def test_otp_is_stored_as_keyed_digest() -> None:
    otp = "123456"

    assert _otp_digest(otp) != otp
    assert _otp_digest(otp) == _otp_digest(otp)


async def test_logout_clears_refresh_cookie_at_matching_path() -> None:
    response = await logout(Response(), refresh_token=None, authorization=None)
    set_cookie = response.headers.getlist("set-cookie")[-1]

    assert "refresh_token=" in set_cookie
    assert "Path=/;" in set_cookie
    assert "Max-Age=0" in set_cookie


def test_login_rate_limit_key_does_not_expose_identity() -> None:
    key = _login_attempt_key("Person@Example.com", "203.0.113.1")

    assert "person@example.com" not in key
    assert "203.0.113.1" not in key
    assert key == _login_attempt_key("person@example.com", "203.0.113.1")


def test_first_failed_login_starts_rate_limit_window() -> None:
    class FakeRedis:
        def __init__(self):
            self.expiration = None

        def incr(self, key):
            return 1

        def expire(self, key, seconds):
            self.expiration = (key, seconds)

    redis = FakeRedis()
    _record_failed_login(redis, "login_attempts:test")

    assert redis.expiration == ("login_attempts:test", LOGIN_ATTEMPT_WINDOW_SECONDS)
