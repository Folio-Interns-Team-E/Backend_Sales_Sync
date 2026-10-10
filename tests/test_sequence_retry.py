from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.team_member import MemberRole
from app.routers.sequences import retry_failed_enrollment


async def test_failed_enrollment_is_queued_without_resetting_progress():
    sequence_id, enrollment_id, team_id, user_id, delivery_id = [uuid4() for _ in range(5)]
    sequence = SimpleNamespace(id=sequence_id, status="Active")
    enrollment = SimpleNamespace(id=enrollment_id, status="Failed", current_step=2, next_send_at=None, completed_at=datetime.now(timezone.utc))
    delivery = SimpleNamespace(id=delivery_id, status="Failed")
    db = SimpleNamespace(scalar=AsyncMock(return_value=delivery), add=Mock(), commit=AsyncMock())
    team_ctx = SimpleNamespace(team_id=team_id, role=MemberRole.admin)
    user = SimpleNamespace(id=user_id)

    with patch("app.routers.sequences.managed_enrollment", new=AsyncMock(return_value=(sequence, enrollment))):
        response = await retry_failed_enrollment(sequence_id, enrollment_id, db, team_ctx, user)

    assert response.success is True
    assert enrollment.status == "Active"
    assert enrollment.current_step == 2
    assert enrollment.next_send_at is not None
    assert enrollment.completed_at is None
    db.commit.assert_awaited_once()
    audit = db.add.call_args.args[0]
    assert audit.action == "sequence.delivery_retry_requested"
    assert audit.target_id == str(delivery_id)


@pytest.mark.parametrize(
    "enrollment_status,sequence_status,message",
    [("Completed", "Active", "Only failed enrollments"), ("Failed", "Paused", "Activate the sequence")],
)
async def test_retry_rejects_invalid_state(enrollment_status, sequence_status, message):
    sequence_id, enrollment_id = uuid4(), uuid4()
    sequence = SimpleNamespace(id=sequence_id, status=sequence_status)
    enrollment = SimpleNamespace(id=enrollment_id, status=enrollment_status)
    db = SimpleNamespace(scalar=AsyncMock(), add=Mock(), commit=AsyncMock())
    team_ctx = SimpleNamespace(team_id=uuid4(), role=MemberRole.admin)

    with patch("app.routers.sequences.managed_enrollment", new=AsyncMock(return_value=(sequence, enrollment))):
        with pytest.raises(HTTPException) as error:
            await retry_failed_enrollment(sequence_id, enrollment_id, db, team_ctx, SimpleNamespace(id=uuid4()))

    assert error.value.status_code == 409
    assert message in error.value.detail
    db.commit.assert_not_awaited()


async def test_retry_requires_a_failed_delivery_record():
    sequence_id, enrollment_id = uuid4(), uuid4()
    sequence = SimpleNamespace(id=sequence_id, status="Active")
    enrollment = SimpleNamespace(id=enrollment_id, status="Failed")
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock(), commit=AsyncMock())
    team_ctx = SimpleNamespace(team_id=uuid4(), role=MemberRole.manager)

    with patch("app.routers.sequences.managed_enrollment", new=AsyncMock(return_value=(sequence, enrollment))):
        with pytest.raises(HTTPException) as error:
            await retry_failed_enrollment(sequence_id, enrollment_id, db, team_ctx, SimpleNamespace(id=uuid4()))

    assert error.value.status_code == 409
    db.commit.assert_not_awaited()
