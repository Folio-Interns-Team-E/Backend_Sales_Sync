from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional

# What the frontend sends when saving/updating
class CalComIntegrationCreate(BaseModel):
    cal_api_key: str = Field(..., description="The plain text API key from Cal.com")
    cal_event_type_id: str = Field(..., description="The event type ID for bookings")

# What you return to the frontend (Never return the API key!)
class CalComIntegrationResponse(BaseModel):
    id: UUID
    user_id: UUID
    event_type_id: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True