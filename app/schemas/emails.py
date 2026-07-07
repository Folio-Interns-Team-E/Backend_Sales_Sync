from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.models.email import EmailStatus


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
    status: EmailStatus
    # 🔧 Change this from created_at to sent_at (or make it optional)
    sent_at: datetime | None = None 
    ai_metadata: dict

    model_config = ConfigDict(from_attributes=True)