from unittest.mock import patch
from uuid import uuid4

import pytest

from app.routers.integrations import gmail_success_redirect_url, settings
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
