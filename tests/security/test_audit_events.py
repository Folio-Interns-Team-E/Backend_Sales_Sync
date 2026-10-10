import io
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.core.observability import JsonFormatter, request_id_context, request_observability
from app.services.audit_service import decode_cursor, list_audit_events, record_audit_event


async def test_audit_query_is_tenant_scoped_and_cursor_is_stable():
    team_id = uuid4()
    now = datetime.now(timezone.utc)
    rows = [
        SimpleNamespace(id=uuid4(), actor_user_id=uuid4(), action="sequence.created", target_type="sequence", target_id=str(uuid4()), created_at=now - timedelta(seconds=index))
        for index in range(3)
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))))

    page = await list_audit_events(db, team_id, limit=2)

    assert len(page.events) == 2
    assert decode_cursor(page.next_cursor) == (rows[1].created_at, rows[1].id)
    query = db.execute.call_args.args[0]
    assert team_id in query.compile().params.values()
    assert "ORDER BY audit_events.created_at DESC, audit_events.id DESC" in str(query)


@pytest.mark.parametrize("cursor", ["garbage", "x" * 257, "aW52YWxpZA=="])
async def test_invalid_audit_cursor_is_rejected_before_query(cursor):
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await list_audit_events(db, uuid4(), cursor=cursor)
    assert error.value.status_code == 400
    db.execute.assert_not_awaited()


def test_audit_event_contains_only_allowlisted_fields():
    db = SimpleNamespace(add=lambda row: setattr(db, "row", row))
    record_audit_event(db, uuid4(), uuid4(), "sequence.deleted", "sequence", uuid4())
    assert set(db.row.__table__.columns.keys()) == {"id", "team_id", "actor_user_id", "action", "target_type", "target_id", "created_at"}


def test_json_formatter_adds_correlation_without_secret_fields():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("audit-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    token = request_id_context.set("request-123")
    try:
        logger.info("request method=GET path=/health status=200 duration_ms=1")
    finally:
        request_id_context.reset(token)
    payload = json.loads(stream.getvalue())
    assert payload["request_id"] == "request-123"
    assert payload["service"]
    assert "query" not in payload and "body" not in payload


async def test_request_middleware_returns_request_id_and_does_not_log_query(caplog):
    app = FastAPI()
    app.middleware("http")(request_observability)

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="sales_sync.http"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/probe?token=top-secret", headers={"X-Request-ID": "safe-id-123"})
    assert response.headers["X-Request-ID"] == "safe-id-123"
    assert "token" not in caplog.text and "top-secret" not in caplog.text
