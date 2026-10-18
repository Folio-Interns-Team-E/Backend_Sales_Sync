from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.routers.integrations import (
    disconnect_gmail,
    disconnect_google_calendar,
    gmail_success_redirect_url,
    settings,
)
from app.services import gmail_service


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, **kwargs):
        assert kwargs == {"ex": 600, "nx": True}
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def getdel(self, key):
        return self.values.pop(key, None)


def test_gmail_callback_returns_to_canonical_frontend_not_first_cors_origin():
    with (
        patch.object(settings, "oauth_frontend_url", "https://salesync.world/"),
        patch.object(settings, "frontend_origins", ["https://temporary-preview.vercel.app"]),
    ):
        assert gmail_success_redirect_url() == "https://salesync.world/settings?integration=success"


def test_gmail_oauth_state_is_browser_bound_and_single_use():
    redis = FakeRedis()
    user_id = uuid4()
    with patch.object(gmail_service, "get_redis", return_value=redis):
        state, binding = gmail_service.begin_gmail_oauth(user_id)
        with pytest.raises(ValueError):
            gmail_service.consume_gmail_oauth(state, "wrong-browser")
        assert gmail_service.consume_gmail_oauth(state, binding) == user_id
        with pytest.raises(ValueError):
            gmail_service.consume_gmail_oauth(state, binding)


def test_google_refresh_token_is_decrypted_before_use():
    credentials = type("Credentials", (), {"encrypted_refresh_token": "ciphertext"})()
    with patch.object(gmail_service, "decrypt_key", return_value="plain-token") as decrypt:
        assert gmail_service.google_refresh_token(credentials) == "plain-token"
        decrypt.assert_called_once_with("ciphertext")


@pytest.mark.asyncio
async def test_google_token_revocation_sends_token_in_request_body():
    response = AsyncMock()
    response.status_code = 200
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client

    with patch.object(gmail_service.httpx, "AsyncClient", return_value=context):
        await gmail_service.revoke_google_token("private-refresh-token")

    client.post.assert_awaited_once_with(
        gmail_service.GOOGLE_REVOKE_URL,
        data={"token": "private-refresh-token"},
    )


@pytest.mark.asyncio
async def test_disconnect_gmail_revokes_and_deletes_credentials():
    user = SimpleNamespace(id=uuid4())
    credentials = SimpleNamespace(encrypted_refresh_token="encrypted")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: credentials)

    with (
        patch("app.routers.integrations.google_refresh_token", return_value="refresh-token"),
        patch("app.routers.integrations.revoke_google_token", new=AsyncMock()) as revoke,
    ):
        response = await disconnect_gmail(user, db)

    revoke.assert_awaited_once_with("refresh-token")
    db.delete.assert_awaited_once_with(credentials)
    db.commit.assert_awaited_once()
    assert response["success"] is True


@pytest.mark.asyncio
async def test_disconnect_calendar_revokes_and_deletes_credentials():
    user = SimpleNamespace(id=uuid4())
    credentials = SimpleNamespace(encrypted_refresh_token="encrypted")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: credentials)

    with (
        patch("app.routers.integrations.decrypt_key", return_value="refresh-token"),
        patch("app.routers.integrations.revoke_google_token", new=AsyncMock()) as revoke,
    ):
        response = await disconnect_google_calendar(user, db)

    revoke.assert_awaited_once_with("refresh-token")
    db.delete.assert_awaited_once_with(credentials)
    db.commit.assert_awaited_once()
    assert response["success"] is True
