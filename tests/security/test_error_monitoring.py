from unittest.mock import patch

from app.core import observability


def test_error_tracking_stays_disabled_without_dsn():
    with patch.object(observability.settings, "sentry_dsn", ""), patch.object(
        observability.sentry_sdk, "init"
    ) as init:
        assert observability.configure_error_tracking() is False
        init.assert_not_called()


def test_error_tracking_uses_safe_production_defaults():
    with (
        patch.object(observability.settings, "sentry_dsn", "https://public@example.invalid/1"),
        patch.object(observability.settings, "sentry_environment", "production"),
        patch.object(observability.settings, "sentry_release", "release-123"),
        patch.object(observability.settings, "sentry_traces_sample_rate", 0.25),
        patch.object(observability.sentry_sdk, "init") as init,
    ):
        assert observability.configure_error_tracking() is True

    kwargs = init.call_args.kwargs
    assert kwargs["environment"] == "production"
    assert kwargs["release"] == "release-123"
    assert kwargs["traces_sample_rate"] == 0.25
    assert kwargs["send_default_pii"] is False


def test_sentry_event_scrubber_removes_credentials_and_personal_data():
    event = {
        "request": {
            "headers": {"Authorization": "Bearer secret", "Accept": "application/json"},
            "cookies": {"session": "secret"},
            "data": {"password": "secret"},
            "query_string": "token=secret",
            "url": "https://api.salesync.world/leads?token=secret",
        },
        "user": {"id": "user-123", "email": "person@example.com", "ip_address": "127.0.0.1"},
    }

    scrubbed = observability._scrub_sentry_event(event, {})

    assert scrubbed["request"]["headers"] == {
        "Authorization": "[Filtered]",
        "Accept": "application/json",
    }
    assert "cookies" not in scrubbed["request"]
    assert "data" not in scrubbed["request"]
    assert "query_string" not in scrubbed["request"]
    assert scrubbed["request"]["url"] == "https://api.salesync.world/leads"
    assert scrubbed["user"] == {"id": "user-123"}
