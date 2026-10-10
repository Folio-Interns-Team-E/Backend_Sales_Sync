from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.routers.notifications import list_notifications, read_all_notifications
from app.services.notification_service import create_notification


def test_notification_creation_is_bounded_and_tenant_owned():
    db = SimpleNamespace(add=Mock())
    team_id, user_id = uuid4(), uuid4()
    row = create_notification(db, team_id, user_id, "k" * 60, "t" * 200, "b" * 600, "/sequences")
    assert row.team_id == team_id
    assert row.user_id == user_id
    assert len(row.kind) == 40
    assert len(row.title) == 160
    assert len(row.body) == 500
    db.add.assert_called_once_with(row)


async def test_notification_list_is_scoped_to_user_and_workspace():
    team_id, user_id = uuid4(), uuid4()
    row = SimpleNamespace(id=uuid4(), kind="lead_replied", title="Lead replied", body="A lead replied.", link="/sequences", is_read=False, created_at=datetime.now(timezone.utc))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))))
    response = await list_notifications(False, 30, db, SimpleNamespace(team_id=team_id), SimpleNamespace(id=user_id))
    assert response.data[0].id == row.id
    statement = db.execute.call_args.args[0]
    params = statement.compile().params.values()
    assert team_id in params and user_id in params


async def test_read_all_is_scoped_and_committed():
    team_id, user_id = uuid4(), uuid4()
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=3)), commit=AsyncMock())
    response = await read_all_notifications(db, SimpleNamespace(team_id=team_id), SimpleNamespace(id=user_id))
    assert response.data == {"updated": 3}
    statement = db.execute.call_args.args[0]
    params = statement.compile().params.values()
    assert team_id in params and user_id in params
    db.commit.assert_awaited_once()
