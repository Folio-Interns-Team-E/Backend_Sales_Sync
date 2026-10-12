from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.inbound_email_service import gmail_after, detect_outreach_replies


def test_gmail_after_uses_epoch_seconds():
    assert gmail_after(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1767225600


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_thread,expected", [("sent-thread", 1), ("other-thread", 0)])
async def test_one_off_reply_notifies_only_for_matching_gmail_thread(reply_thread, expected):
    sender_id, team_id = uuid4(), uuid4()
    email = SimpleNamespace(
        id=uuid4(), sent_at=datetime.now(timezone.utc),
        ai_metadata={"sender_user_id": str(sender_id), "provider_message_id": "sent-message"},
    )
    lead = SimpleNamespace(email="prospect@example.com", name="Prospect", team_id=team_id, status="Sent")
    db = SimpleNamespace(execute=AsyncMock(return_value=MagicMock(all=lambda: [(email, lead)])),
                         scalar=AsyncMock(return_value=object()), commit=AsyncMock())

    async def thread_id(_token, message_id):
        return "sent-thread" if message_id == "sent-message" else reply_thread

    with patch("app.services.inbound_email_service.google_refresh_token", return_value="token"), \
         patch("app.services.inbound_email_service.get_gmail_thread_id", side_effect=thread_id), \
         patch("app.services.inbound_email_service.search_gmail_messages", new=AsyncMock(return_value=[{"id": "reply-message"}])), \
         patch("app.services.inbound_email_service.create_notification") as notify:
        result = await detect_outreach_replies(db)

    assert result["replied"] == expected
    assert notify.call_count == expected
    assert ("reply_notified_at" in email.ai_metadata) == bool(expected)
    assert lead.status == ("Replied" if expected else "Sent")
    db.commit.assert_awaited_once()
