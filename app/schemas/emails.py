from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class EmailCreate(BaseModel):
    lead_id: UUID
    subject: str
    body: str
    tone: Optional[str] = "Professional"


class EmailResponse(BaseModel):
    id: UUID
    lead_id: UUID
    subject: str
    body: str
    status: str
    sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
