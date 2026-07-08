from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class KnowledgeAssetCreate(BaseModel):
    title: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class KnowledgeAssetResponse(BaseModel):
    id: UUID
    team_id: UUID
    title: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    file_url: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
