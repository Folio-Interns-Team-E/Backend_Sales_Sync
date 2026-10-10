from datetime import datetime, timezone

from app.services.inbound_email_service import gmail_after


def test_gmail_after_uses_epoch_seconds():
    assert gmail_after(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1767225600
