from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class KnowledgeAssetUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None


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
    source_url: Optional[str] = None
    status: Optional[str] = None
    embedding_id: Optional[str] = None
    chunk_count: int = 0
    indexed_at: Optional[datetime] = None
    processing_error: Optional[str] = None
    presigned_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class KnowledgeBaseSearchRequest(BaseModel):
    query: str
    limit: int = 5


class KnowledgeBaseSource(BaseModel):
    asset_id: UUID
    asset_title: str
    chunk_index: int
    score: float
    content: str
    source_url: Optional[str] = None


class KnowledgeBaseSearchResponse(BaseModel):
    query: str
    sources: List[KnowledgeBaseSource]


class KnowledgeBaseAnswerResponse(BaseModel):
    query: str
    answer: str
    sources: List[KnowledgeBaseSource]
