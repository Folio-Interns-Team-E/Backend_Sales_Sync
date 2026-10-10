import base64
import binascii
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, tuple_

from app.models.audit_event import AuditEvent
from app.schemas.audit import AuditEventResponse, AuditPage


def record_audit_event(db, team_id: UUID, actor_user_id: UUID, action: str, target_type: str, target_id=None) -> None:
    if not action or len(action) > 80 or not target_type or len(target_type) > 40:
        raise ValueError("Invalid audit event")
    db.add(AuditEvent(team_id=team_id, actor_user_id=actor_user_id, action=action, target_type=target_type, target_id=str(target_id)[:100] if target_id else None))


def encode_cursor(event: AuditEvent) -> str:
    return base64.urlsafe_b64encode(f"{event.created_at.isoformat()}|{event.id}".encode()).decode()


def decode_cursor(cursor: str):
    try:
        if len(cursor) > 256: raise ValueError()
        timestamp, event_id = base64.b64decode(cursor, altchars=b"-_", validate=True).decode().split("|")
        created_at = datetime.fromisoformat(timestamp)
        if created_at.tzinfo is None: raise ValueError()
        return created_at.astimezone(timezone.utc), UUID(event_id)
    except (ValueError, UnicodeError, binascii.Error):
        raise HTTPException(400, "Invalid audit cursor")


async def list_audit_events(db, team_id: UUID, limit=50, cursor=None):
    statement = select(AuditEvent).where(AuditEvent.team_id == team_id)
    if cursor:
        created_at, event_id = decode_cursor(cursor)
        statement = statement.where(tuple_(AuditEvent.created_at, AuditEvent.id) < tuple_(created_at, event_id))
    rows = list((await db.execute(statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1))).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(events=[AuditEventResponse.model_validate(row) for row in rows], next_cursor=encode_cursor(rows[-1]) if has_more else None)
