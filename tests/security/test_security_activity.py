from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.models.security_event import SecurityAction, SecurityEvent
from app.routers.security_activity import router
from app.schemas.auth import LoginRequest
from app.services.auth_service import login_user
from app.services.security_activity import record_security_event, list_security_activity, encode_cursor, decode_cursor
from app.services.social_auth import resolve_user
from app.core.security import session_claims


@pytest.fixture
def activity_db():
    # An isolated, disposable database; no real accounts or external services.
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    SecurityEvent.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


async def test_account_isolation_executes_real_query(activity_db):
    actor, other = uuid4(), uuid4()
    record_security_event(activity_db, actor, SecurityAction.password_login)
    record_security_event(activity_db, other, SecurityAction.password_reset)
    activity_db.commit()
    db = SimpleNamespace(execute=AsyncMock(side_effect=activity_db.execute))
    page = await list_security_activity(db, actor)
    assert [event.action for event in page.events] == [SecurityAction.password_login]
    assert set(page.events[0].model_dump()) == {"id", "action", "created_at"}


def test_event_rolls_back_with_transaction(activity_db):
    record_security_event(activity_db, uuid4(), SecurityAction.password_reset)
    activity_db.flush()
    activity_db.rollback()
    assert activity_db.execute(select(SecurityEvent)).scalars().all() == []


def test_event_rejects_arbitrary_secret_metadata(activity_db):
    with pytest.raises(ValueError):
        record_security_event(activity_db, uuid4(), "password=secret")
    assert not activity_db.new


async def test_pagination_has_stable_cursor_and_bound_user():
    actor = uuid4()
    now = datetime.now(timezone.utc)
    rows = [SimpleNamespace(id=uuid4(), action=SecurityAction.password_login, created_at=now - timedelta(seconds=i)) for i in range(3)]
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))))
    page = await list_security_activity(db, actor, limit=2)
    assert len(page.events) == 2
    assert decode_cursor(page.next_cursor) == (rows[1].created_at, rows[1].id)
    await list_security_activity(db, actor, limit=2, cursor=page.next_cursor)
    query = db.execute.call_args.args[0]
    params = query.compile().params
    assert actor in params.values()
    assert rows[1].id in params.values()
    assert "ORDER BY security_events.created_at DESC, security_events.id DESC" in str(query)


@pytest.mark.parametrize("cursor", ["garbage", "x" * 257, "aW52YWxpZA=="])
async def test_invalid_cursor_rejected_before_query(cursor):
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await list_security_activity(db, uuid4(), cursor=cursor)
    assert error.value.status_code == 400
    db.execute.assert_not_awaited()


async def test_history_route_ignores_supplied_other_user_and_disables_caching():
    actor, other = uuid4(), uuid4()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=actor)
    app.dependency_overrides[get_db] = lambda: None
    with patch("app.routers.security_activity.list_security_activity", new=AsyncMock(return_value={"events": [], "next_cursor": None})) as service:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/auth/activity?user_id={other}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    service.assert_awaited_once_with(None, actor, 25, None)


async def test_history_requires_authentication():
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/auth/activity")).status_code in (401, 403)


@pytest.mark.parametrize("matches,verified,expected", [(True, True, True), (False, True, False), (True, False, False)])
async def test_only_successful_verified_password_login_is_recorded(matches, verified, expected):
    user = SimpleNamespace(id=uuid4(), email="person@example.com", full_name="Person", email_verified=verified, hashed_password="hash")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user)), add=Mock(), commit=AsyncMock())
    with patch("app.services.auth_service.get_redis", return_value=None), patch("app.services.auth_service.verify_password", return_value=matches):
        if matches:
            await login_user(LoginRequest(email=user.email, password="test-password"), db)
        else:
            with pytest.raises(HTTPException):
                await login_user(LoginRequest(email=user.email, password="test-password"), db)
    assert db.add.called is expected
    assert db.commit.called is expected
    if expected:
        assert db.add.call_args.args[0].action == SecurityAction.password_login
        assert db.add.call_args.args[0].user_id == user.id


async def test_provider_link_event_commits_with_identity():
    user = SimpleNamespace(id=uuid4(), email_verified=True, hashed_password="hash")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[SimpleNamespace(scalar_one_or_none=lambda: None), SimpleNamespace(scalar_one_or_none=lambda: user)]), add=Mock(), commit=AsyncMock())
    await resolve_user(db, "google", "subject", "person@example.com", "Person", session_claims(user))
    assert db.add.call_args.args[0].action == SecurityAction.google_linked
    assert db.add.call_args.args[0].user_id == user.id
    db.commit.assert_awaited_once()
