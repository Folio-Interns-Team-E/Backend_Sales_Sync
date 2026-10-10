from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    actor_user_id: UUID | None
    action: str
    target_type: str
    target_id: str | None
    created_at: datetime


class AuditPage(BaseModel):
    events: list[AuditEventResponse]
    next_cursor: str | None = None
