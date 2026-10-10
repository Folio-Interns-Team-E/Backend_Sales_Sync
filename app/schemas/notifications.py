from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str
    link: str | None
    is_read: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
