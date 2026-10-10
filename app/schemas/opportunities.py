from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.opportunity import OpportunityStage


class OpportunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    lead_id: Optional[UUID] = None
    owner_id: Optional[UUID] = None
    stage: OpportunityStage = OpportunityStage.PROSPECTING
    amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    probability: int = Field(default=10, ge=0, le=100)
    expected_close_date: Optional[date] = None
    loss_reason: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_loss_reason(self):
        if self.stage != OpportunityStage.CLOSED_LOST:
            self.loss_reason = None
        return self


class OpportunityUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    company_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    lead_id: Optional[UUID] = None
    owner_id: Optional[UUID] = None
    stage: Optional[OpportunityStage] = None
    amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    probability: Optional[int] = Field(default=None, ge=0, le=100)
    expected_close_date: Optional[date] = None
    loss_reason: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else value


class OpportunityResponse(BaseModel):
    id: UUID
    team_id: UUID
    lead_id: Optional[UUID]
    owner_id: Optional[UUID]
    owner_name: Optional[str] = None
    name: str
    company_name: str
    stage: str
    amount: Decimal
    currency: str
    probability: int
    expected_close_date: Optional[date]
    loss_reason: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OpportunitySummary(BaseModel):
    total_count: int
    open_count: int
    won_count: int
    lost_count: int
    pipeline_value: Decimal
    weighted_value: Decimal
    won_value: Decimal
