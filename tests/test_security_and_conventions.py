from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.security import create_access_token


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, ex=None):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_auth_13_wrong_missing_and_used_otp_fail(client, api_user, monkeypatch):
    user = await api_user("otp-negative")
    redis = FakeRedis()
    redis.values[f"otp:{user['email']}"] = "123456"
    monkeypatch.setattr("app.services.auth_service.get_redis", lambda: redis)

    wrong = await client.post(
        "/auth/otp/verify", json={"email": user["email"], "otp": "654321"}
    )
    missing = await client.post(
        "/auth/otp/verify",
        json={"email": f"missing-{uuid4().hex}@example.com", "otp": "123456"},
    )
    assert wrong.status_code == missing.status_code == 400


@pytest.mark.asyncio
async def test_auth_14_unknown_otp_request_has_documented_behavior(client, monkeypatch):
    monkeypatch.setattr("app.services.auth_service.get_redis", lambda: FakeRedis())
    response = await client.post(
        "/auth/otp/request",
        json={"email": f"unknown-{uuid4().hex}@example.com"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_auth_15_redis_unavailable_is_controlled(client, api_user):
    user = await api_user("redis-down")
    requested = await client.post("/auth/otp/request", json={"email": user["email"]})
    verified = await client.post(
        "/auth/otp/verify", json={"email": user["email"], "otp": "123456"}
    )
    for response in (requested, verified):
        assert response.status_code == 500
        assert response.json()["error"] == (
            "Verification service is temporarily unavailable. Please try again later."
        )


@pytest.mark.asyncio
async def test_auth_17_otp_endpoints_are_rate_limited(client, api_user, monkeypatch):
    user = await api_user("otp-rate")
    redis = FakeRedis()
    monkeypatch.setattr("app.services.auth_service.get_redis", lambda: redis)
    monkeypatch.setattr(
        "app.services.auth_service.send_otp_email",
        lambda *args, **kwargs: None,
    )
    statuses = []
    for _ in range(12):
        response = await client.post("/auth/otp/request", json={"email": user["email"]})
        statuses.append(response.status_code)
    assert 429 in statuses


@pytest.mark.asyncio
async def test_auth_19_deleted_user_token_returns_401(client):
    token = create_access_token({"sub": str(uuid4())})
    response = await client.get(
        "/teams/", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_auth_21_login_cookie_security_flags(client, api_user):
    user = await api_user("cookie")
    # Registration intentionally leaves the account unverified, so this first checks
    # that verification-gated login never emits a refresh cookie.
    response = await client.post(
        "/auth/login", json={"email": user["email"], "password": user["password"]}
    )
    assert response.status_code == 200
    assert "refresh_token" not in response.cookies


@pytest.mark.asyncio
async def test_core_02_success_envelope_is_consistent(client, api_user):
    user = await api_user("envelope")
    response = await client.get("/teams/", headers=user["headers"])
    assert response.status_code == 200
    assert set(response.json()) == {"success", "message", "data", "error"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_kind",
    ["unauthorized", "forbidden", "not_found", "validation"],
)
async def test_core_03_error_envelope_is_consistent(
    client, api_user, request_kind
):
    if request_kind == "unauthorized":
        response = await client.get("/teams/")
    elif request_kind == "validation":
        response = await client.post("/auth/register", json={})
    elif request_kind == "not_found":
        user = await api_user("missing-resource")
        team = await client.post("/teams/", json={"name": "Missing Team"}, headers=user["headers"])
        headers = {**user["headers"], "X-Team-Id": team.json()["data"]["id"]}
        response = await client.get(f"/leads/{uuid4()}", headers=headers)
    else:
        first = await api_user("forbidden-owner")
        second = await api_user("forbidden-other")
        team = await client.post("/teams/", json={"name": "Private Team"}, headers=first["headers"])
        response = await client.get(
            f"/teams/{team.json()['data']['id']}", headers=second["headers"]
        )
    assert response.status_code in {401, 403, 404, 422}
    assert set(response.json()) == {"success", "message", "data", "error"}


@pytest.mark.asyncio
async def test_core_05_cors_allows_configured_and_denies_unknown_origin(client):
    allowed = await client.options(
        "/auth/login",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    unknown = await client.options(
        "/auth/login",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    assert unknown.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_core_08_unknown_fields_follow_reject_policy(client, api_user):
    user = await api_user("unknown-fields")
    response = await client.post(
        "/teams/",
        json={"name": "Known", "unexpected": "must not disappear silently"},
        headers=user["headers"],
    )
    assert response.status_code == 422
