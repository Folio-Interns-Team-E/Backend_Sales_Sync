from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from app.models.security_event import SecurityAction


class SecurityEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: SecurityAction
    created_at: datetime


class SecurityActivityPage(BaseModel):
    events: list[SecurityEventResponse]
    next_cursor: str | None = None
