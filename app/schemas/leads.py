from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class LeadCreate(BaseModel):
    name: str
    company: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    source: Optional[str] = None


class LeadUpdate(BaseModel):
    status: Optional[str] = None
    score: Optional[int] = None
    reasoning: Optional[str] = None


class LeadResponse(BaseModel):
    id: UUID
    team_id: UUID
    name: str
    email: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    score: Optional[int] = None
    status: str
    reasoning: Optional[str] = None
    pool_origin_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj):
        data = {
            "id": obj.id,
            "team_id": obj.team_id,
            "name": obj.name,
            "email": obj.email,
            "company": getattr(obj, "company_name", None),
            "title": getattr(obj, "job_title", None),
            "source": getattr(obj, "source", None),
            "score": int(obj.score) if obj.score else None,
            "status": obj.status if isinstance(obj.status, str) else obj.status.value,
            "reasoning": (obj.ai_context_data or {}).get("reasoning") if hasattr(obj, "ai_context_data") else None,
            "pool_origin_id": getattr(obj, "pool_origin_id", None),
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
        return super().model_validate(data)


class LeadListResponse(BaseModel):
    id: UUID
    name: str
    email: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    score: Optional[int] = None
    status: str
    reasoning: Optional[str] = None
    pool_origin_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj):
        data = {
            "id": obj.id,
            "name": obj.name,
            "email": obj.email,
            "company": getattr(obj, "company_name", None),
            "title": getattr(obj, "job_title", None),
            "source": getattr(obj, "source", None),
            "score": int(obj.score) if obj.score else None,
            "status": obj.status if isinstance(obj.status, str) else obj.status.value,
            "reasoning": (obj.ai_context_data or {}).get("reasoning") if hasattr(obj, "ai_context_data") else None,
            "pool_origin_id": getattr(obj, "pool_origin_id", None),
            "created_at": obj.created_at,
        }
        return super().model_validate(data)
