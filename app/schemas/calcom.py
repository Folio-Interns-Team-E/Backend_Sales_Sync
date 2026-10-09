from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from datetime import datetime
from typing import Optional

# What the frontend sends when saving/updating
class CalComIntegrationCreate(BaseModel):
    cal_api_key: str = Field(..., min_length=8, max_length=500, description="The plain text API key from Cal.com")
    cal_event_type_id: str = Field(..., min_length=1, max_length=32, description="The event type ID for bookings")

# What you return to the frontend (Never return the API key!)
class CalComIntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    event_type_id: str
    created_at: datetime
    updated_at: Optional[datetime]

class CalComStatus(BaseModel):
    connected: bool
    event_type_id: Optional[str] = None
    needs_event_type: bool = False


class CalComEventTypeUpdate(BaseModel):
    event_type_id: str = Field(..., min_length=1, max_length=32)
