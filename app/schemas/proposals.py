from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class ProposalCreate(BaseModel):
    lead_id: Optional[UUID] = None
    company: str
    title: str = "New Proposal"
    summary: Optional[str] = None
    value: Optional[float] = None


class ProposalUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    value: Optional[float] = None
    status: Optional[str] = None
    outcome: Optional[str] = None


class ProposalRevisionCreate(BaseModel):
    title: str
    summary: str
    value: Optional[float] = None
    note: str = ""


class ProposalRevisionResponse(BaseModel):
    id: UUID
    proposal_id: UUID
    revision_num: int
    title: Optional[str] = None
    summary: Optional[str] = None
    value: Optional[float] = None
    edited_by: Optional[UUID] = None
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProposalResponse(BaseModel):
    id: UUID
    team_id: UUID
    lead_id: Optional[UUID] = None
    company: str
    title: str
    summary: Optional[str] = None
    value: Optional[float] = None
    status: str
    outcome: str
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProposalTemplateUpdate(BaseModel):
    template_name: Optional[str] = None
    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    sections: Optional[list[dict]] = None


class ProposalTemplateResponse(BaseModel):
    id: UUID
    team_id: UUID
    template_name: str
    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    sections: list[dict] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
