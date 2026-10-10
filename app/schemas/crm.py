from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AccountPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=120)
    employee_count: Optional[str] = Field(default=None, max_length=50)
    annual_revenue: Optional[Decimal] = Field(default=None, ge=0)
    country: Optional[str] = Field(default=None, max_length=100)
    owner_id: Optional[UUID] = None
    notes: Optional[str] = None


class AccountUpdate(AccountPayload):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)


class AccountResponse(AccountPayload):
    id: UUID
    team_id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ContactPayload(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(default="", max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    job_title: Optional[str] = Field(default=None, max_length=150)
    lifecycle_stage: Literal["Lead", "Marketing Qualified", "Sales Qualified", "Customer", "Other"] = "Lead"
    account_id: Optional[UUID] = None
    owner_id: Optional[UUID] = None
    notes: Optional[str] = None


class ContactUpdate(ContactPayload):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)


class ContactResponse(ContactPayload):
    id: UUID
    team_id: UUID
    account_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    task_type: Literal["Follow-up", "Email", "Call", "Meeting", "General"] = "Follow-up"
    priority: Literal["Low", "Medium", "High", "Urgent"] = "Medium"
    status: Literal["Open", "In Progress", "Completed", "Cancelled"] = "Open"
    due_at: Optional[datetime] = None
    owner_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    opportunity_id: Optional[UUID] = None
    description: Optional[str] = None


class TaskUpdate(TaskPayload):
    title: Optional[str] = Field(default=None, min_length=1, max_length=240)


class TaskResponse(TaskPayload):
    id: UUID
    team_id: UUID
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SearchResult(BaseModel):
    id: UUID
    type: str
    title: str
    subtitle: str
    url: str
