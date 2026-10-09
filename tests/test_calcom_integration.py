from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.calcom_service import begin_calcom_oauth, cal_headers, consume_calcom_oauth, verify_calcom_credentials


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, **kwargs):
        self.values[key] = value
        assert kwargs == {"ex": 600, "nx": True}
        return True

    def get(self, key):
        return self.values.get(key)

    def getdel(self, key):
        return self.values.pop(key, None)


def test_calcom_headers_never_put_secret_in_the_url():
    headers = cal_headers("cal_live_secret")
    assert headers["Authorization"] == "Bearer cal_live_secret"
    assert headers["cal-api-version"]


def test_calcom_oauth_state_is_browser_bound_and_single_use():
    redis = FakeRedis()
    user_id, team_id = uuid4(), uuid4()
    with (
        patch("app.services.calcom_service.get_redis", return_value=redis),
        patch("app.services.calcom_service.settings.cal_oauth_client_id", "client-id"),
        patch("app.services.calcom_service.settings.cal_oauth_client_secret", "client-secret"),
    ):
        url, binding = begin_calcom_oauth(user_id, team_id)
        state = parse_qs(urlsplit(url).query)["state"][0]
        assert "client-secret" not in url
        with pytest.raises(HTTPException):
            consume_calcom_oauth(state, "another-browser")
        record = consume_calcom_oauth(state, binding)
        assert record["user_id"] == str(user_id)
        assert record["team_id"] == str(team_id)
        with pytest.raises(HTTPException):
            consume_calcom_oauth(state, binding)


async def test_calcom_rejects_invalid_credentials_before_storage():
    client = AsyncMock()
    client.get.return_value = SimpleNamespace(status_code=401)
    with patch("app.services.calcom_service.httpx.AsyncClient") as client_factory:
        client_factory.return_value.__aenter__.return_value = client
        with pytest.raises(HTTPException) as error:
            await verify_calcom_credentials("invalid-key", "123")
    assert error.value.status_code == 422


async def test_calcom_accepts_verified_event_type():
    client = AsyncMock()
    client.get.return_value = SimpleNamespace(status_code=200)
    with patch("app.services.calcom_service.httpx.AsyncClient") as client_factory:
        client_factory.return_value.__aenter__.return_value = client
        await verify_calcom_credentials("cal_live_valid", "123")
    requested_url = client.get.await_args.args[0]
    assert requested_url.endswith("/event-types/123")
