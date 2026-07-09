from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class ProposalCreate(BaseModel):
    file_url: str
    lead_id: Optional[UUID] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    template_id: Optional[UUID] = None
    ai_metadata: Optional[dict] = None


class ProposalUpdate(BaseModel):
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    lead_id: Optional[UUID] = None
    template_id: Optional[UUID] = None
    ai_metadata: Optional[dict] = None


class ProposalResponse(BaseModel):
    id: UUID
    lead_id: Optional[UUID] = None
    template_id: Optional[UUID] = None
    status: str
    outcome: str
    file_url: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    version: int
    ai_metadata: dict
    presigned_url: Optional[str] = None
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProposalTemplateUpdate(BaseModel):
    template_name: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None


class ProposalTemplateResponse(BaseModel):
    id: UUID
    team_id: UUID
    template_name: str
    file_url: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    presigned_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ProposalStatusUpdate(BaseModel):
    status: str

class ProposalOutcomeUpdate(BaseModel):
    outcome: str
