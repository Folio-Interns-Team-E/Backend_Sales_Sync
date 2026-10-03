from unittest.mock import patch

from app.core import redis as provider


def test_native_redis_takes_priority_and_decodes_responses():
    with (
        patch.object(provider, "_redis", None),
        patch.object(provider.settings, "redis_url", "redis://127.0.0.1:6379/0"),
        patch.object(provider.NativeRedis, "from_url") as native,
        patch.object(provider, "Redis") as upstash,
    ):
        assert provider.get_redis() is native.return_value
        assert provider.get_redis() is native.return_value
        native.assert_called_once_with("redis://127.0.0.1:6379/0", decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
        upstash.assert_not_called()


def test_upstash_remains_available_without_native_url():
    with (
        patch.object(provider, "_redis", None),
        patch.object(provider.settings, "redis_url", ""),
        patch.object(provider.settings, "upstash_redis_rest_url", "https://example.invalid"),
        patch.object(provider.settings, "upstash_redis_rest_token", "test-token"),
        patch.object(provider, "Redis") as upstash,
    ):
        assert provider.get_redis() is upstash.return_value
        upstash.assert_called_once_with(url="https://example.invalid", token="test-token")
