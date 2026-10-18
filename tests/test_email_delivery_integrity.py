from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routers.emails import _deliver_email


@pytest.mark.asyncio
async def test_delivery_marks_email_sent_only_after_gmail_accepts_it():
    email = SimpleNamespace(
        id=uuid4(),
        subject="A useful subject",
        body="A useful message",
    )
    lead = SimpleNamespace(email="prospect@example.com")
    sent_email = SimpleNamespace(id=email.id, status="sent")
    service = SimpleNamespace(
        get_delivery_target=AsyncMock(return_value=(email, lead)),
        mark_sent=AsyncMock(return_value=sent_email),
    )
    user_id, team_id = uuid4(), uuid4()

    with patch(
        "app.routers.emails.send_email_on_behalf_of_user",
        new=AsyncMock(return_value="gmail-message-id"),
    ) as gmail_send:
        result = await _deliver_email(service, AsyncMock(), email.id, team_id, user_id)

    gmail_send.assert_awaited_once()
    service.mark_sent.assert_awaited_once_with(email, lead, user_id, "gmail-message-id")
    assert result is sent_email


@pytest.mark.asyncio
async def test_delivery_failure_keeps_email_as_a_retryable_draft():
    email = SimpleNamespace(id=uuid4(), subject="Subject", body="Body")
    lead = SimpleNamespace(email="prospect@example.com")
    service = SimpleNamespace(
        get_delivery_target=AsyncMock(return_value=(email, lead)),
        mark_sent=AsyncMock(),
    )

    with patch(
        "app.routers.emails.send_email_on_behalf_of_user",
        new=AsyncMock(side_effect=RuntimeError("Google unavailable")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _deliver_email(service, AsyncMock(), email.id, uuid4(), uuid4())

    assert exc_info.value.status_code == 502
    assert "Reconnect Gmail" in exc_info.value.detail
    service.mark_sent.assert_not_awaited()
