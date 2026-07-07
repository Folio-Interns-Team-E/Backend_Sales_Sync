from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime, date, time


class MeetingCreate(BaseModel):
    lead_id: Optional[UUID] = None
    client: str
    company: Optional[str] = None
    date: date
    time: time
    duration: str = "30 minutes"
    agenda: list[str] = []
    notes: Optional[str] = None


class MeetingUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    transcript: Optional[list[str]] = None
    agenda: Optional[list[str]] = None


class MeetingResponse(BaseModel):
    id: UUID
    team_id: UUID
    lead_id: Optional[UUID] = None
    client: Optional[str] = None
    company: Optional[str] = None
    date: date
    time: time
    duration: Optional[str] = None
    timezone: str
    agenda: list[str]
    transcript: list[str]
    notes: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
