from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class StepInput(BaseModel):
    position: int = Field(ge=0)
    delay_days: int = Field(default=0, ge=0, le=90)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)


class SequenceInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = "Asia/Karachi"
    daily_limit: int = Field(default=40, ge=1, le=500)
    stop_on_reply: bool = True
    steps: list[StepInput] = Field(min_length=1, max_length=20)


class SequenceStatusInput(BaseModel):
    status: Literal["Draft", "Active", "Paused", "Archived"]


class EnrollmentInput(BaseModel):
    lead_ids: list[UUID] = Field(min_length=1, max_length=500)


class StepResponse(StepInput):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class SequenceResponse(BaseModel):
    id: UUID
    team_id: UUID
    owner_id: UUID
    name: str
    status: str
    timezone: str
    daily_limit: int
    stop_on_reply: bool
    steps: list[StepResponse] = []
    active_enrollments: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
