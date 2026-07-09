from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime, date, time


class MeetingCreate(BaseModel):
    lead_id: UUID
    date: date
    time: time
    timezone: str = "UTC"
    calendar_event_id: Optional[str] = None
    agenda: Optional[str] = None
    notes: Optional[str] = None


class MeetingUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    agenda: Optional[str] = None
    date: Optional[date] = None
    time: Optional[time] = None
    timezone: Optional[str] = None
    calendar_event_id: Optional[str] = None


class MeetingResponse(BaseModel):
    id: UUID
    lead_id: UUID
    date: date
    time: time
    timezone: str
    calendar_event_id: Optional[str] = None
    agenda: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
