from unittest.mock import patch

from app.routers.integrations import gmail_success_redirect_url, settings


def test_gmail_callback_returns_to_canonical_frontend_not_first_cors_origin():
    with (
        patch.object(settings, "oauth_frontend_url", "https://salesync.world/"),
        patch.object(settings, "frontend_origins", ["https://temporary-preview.vercel.app"]),
    ):
        assert gmail_success_redirect_url() == "https://salesync.world/settings?integration=success"
