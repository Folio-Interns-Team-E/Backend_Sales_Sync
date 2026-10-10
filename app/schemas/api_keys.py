from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default=90, ge=1, le=365)


class ApiKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
