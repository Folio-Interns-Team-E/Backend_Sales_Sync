from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.chat import ChatRole
from app.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_feedback_is_saved_per_user_without_overwriting_other_members():
    first_user, second_user = uuid4(), uuid4()
    message = SimpleNamespace(
        sent_by=ChatRole.AI.value,
        metadata_log={
            "feedback_by_user": {
                str(first_user): {"rating": "up", "updated_at": "earlier"}
            }
        },
    )
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    service = ChatService(db)
    service.get_message = AsyncMock(return_value=message)

    rating = await service.rate_message(
        uuid4(), uuid4(), second_user, "down", "incorrect"
    )

    assert rating == "down"
    assert message.metadata_log["feedback_by_user"][str(first_user)]["rating"] == "up"
    assert message.metadata_log["feedback_by_user"][str(second_user)]["rating"] == "down"
    assert message.metadata_log["feedback_by_user"][str(second_user)]["reason"] == "incorrect"
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_user_messages_cannot_be_rated():
    message = SimpleNamespace(sent_by=ChatRole.USER.value, metadata_log={})
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    service = ChatService(db)
    service.get_message = AsyncMock(return_value=message)

    with pytest.raises(HTTPException) as error:
        await service.rate_message(uuid4(), uuid4(), uuid4(), "up")

    assert error.value.status_code == 400
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_feedback_requires_a_structured_reason():
    message = SimpleNamespace(sent_by=ChatRole.AI.value, metadata_log={})
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    service = ChatService(db)
    service.get_message = AsyncMock(return_value=message)

    with pytest.raises(HTTPException) as error:
        await service.rate_message(uuid4(), uuid4(), uuid4(), "down")

    assert error.value.status_code == 422
    db.commit.assert_not_awaited()
