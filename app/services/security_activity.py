import base64
import binascii
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, tuple_

from app.models.security_event import SecurityEvent, SecurityAction
from app.schemas.security_activity import SecurityActivityPage, SecurityEventResponse


def record_security_event(db, user_id: UUID, action: SecurityAction) -> None:
    """Participates in the caller's transaction; never independently commits."""
    db.add(SecurityEvent(user_id=user_id, action=SecurityAction(action)))


def encode_cursor(event: SecurityEvent) -> str:
    value = f"{event.created_at.isoformat()}|{event.id}"
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str):
    try:
        if len(cursor) > 256:
            raise ValueError()
        timestamp, event_id = base64.b64decode(cursor, altchars=b"-_", validate=True).decode().split("|")
        created_at = datetime.fromisoformat(timestamp)
        if created_at.tzinfo is None:
            raise ValueError()
        return created_at.astimezone(timezone.utc), UUID(event_id)
    except (ValueError, UnicodeError, binascii.Error):
        raise HTTPException(400, "Invalid activity cursor")


async def list_security_activity(db, user_id: UUID, limit: int = 25, cursor: str | None = None):
    if not 1 <= limit <= 100:
        raise HTTPException(400, "Activity limit must be between 1 and 100")
    statement = select(SecurityEvent).where(SecurityEvent.user_id == user_id)
    if cursor:
        created_at, event_id = decode_cursor(cursor)
        statement = statement.where(tuple_(SecurityEvent.created_at, SecurityEvent.id) < tuple_(created_at, event_id))
    statement = statement.order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc()).limit(limit + 1)
    rows = list((await db.execute(statement)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return SecurityActivityPage(
        events=[SecurityEventResponse.model_validate(row) for row in rows],
        next_cursor=encode_cursor(rows[-1]) if has_more else None,
    )
