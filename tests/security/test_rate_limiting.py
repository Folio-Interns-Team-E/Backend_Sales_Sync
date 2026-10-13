from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.middleware.rate_limit import RateLimitPolicy, rate_limit


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expirations[key] = ex
        return True


def request(ip="203.0.113.10", headers=None):
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": raw_headers,
            "client": (ip, 12345),
        }
    )


@pytest.mark.asyncio
async def test_rate_limit_sets_headers_and_rejects_excess_requests():
    store = FakeRedis()
    dependency = rate_limit(RateLimitPolicy("test-action", 2, 60), "ip")

    with patch("app.middleware.rate_limit.get_redis", return_value=store):
        first_response = Response()
        await dependency(request(), first_response)
        assert first_response.headers["X-RateLimit-Limit"] == "2"
        assert first_response.headers["X-RateLimit-Remaining"] == "1"

        second_response = Response()
        await dependency(request(), second_response)
        assert second_response.headers["X-RateLimit-Remaining"] == "0"

        with pytest.raises(HTTPException) as exc_info:
            await dependency(request(), Response())

    assert exc_info.value.status_code == 429
    assert int(exc_info.value.headers["Retry-After"]) >= 1
    assert len(store.values) == 1


@pytest.mark.asyncio
async def test_workspace_and_user_limits_are_both_enforced():
    store = FakeRedis()
    dependency = rate_limit(RateLimitPolicy("costly-action", 1, 60), "user", "team")
    headers = {"authorization": "Bearer token", "x-team-id": "TEAM-123"}

    with (
        patch("app.middleware.rate_limit.get_redis", return_value=store),
        patch("app.middleware.rate_limit._bearer_subject", return_value="user-456"),
    ):
        await dependency(request(headers=headers), Response())
        with pytest.raises(HTTPException) as exc_info:
            await dependency(request(headers=headers), Response())

    assert exc_info.value.status_code == 429
    assert len(store.values) == 2
    assert all(value == 2 for value in store.values.values())


@pytest.mark.asyncio
async def test_rate_limit_fails_open_outside_production_when_redis_is_unavailable():
    dependency = rate_limit(RateLimitPolicy("test-action", 1, 60), "ip")

    with (
        patch("app.middleware.rate_limit.get_redis", return_value=None),
        patch("app.middleware.rate_limit.settings.app_env", "test"),
    ):
        await dependency(request(), Response())


@pytest.mark.asyncio
async def test_rate_limit_fails_closed_in_production_when_redis_is_unavailable():
    dependency = rate_limit(RateLimitPolicy("test-action", 1, 60), "ip")

    with (
        patch("app.middleware.rate_limit.get_redis", return_value=None),
        patch("app.middleware.rate_limit.settings.app_env", "production"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dependency(request(), Response())

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers["Retry-After"] == "30"
