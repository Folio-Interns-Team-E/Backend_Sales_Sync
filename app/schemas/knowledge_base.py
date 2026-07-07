from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime, date


class KnowledgeAssetCreate(BaseModel):
    title: str
    type: str = "Document"
    company: Optional[str] = None
    date: Optional[date] = None
    description: Optional[str] = None
    file_url: Optional[str] = None
    source_url: Optional[str] = None


class KnowledgeAssetResponse(BaseModel):
    id: UUID
    team_id: UUID
    title: str
    type: str
    company: Optional[str] = None
    date: Optional[date] = None
    description: Optional[str] = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
