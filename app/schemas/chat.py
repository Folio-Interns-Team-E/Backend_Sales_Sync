from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


class ChatMessageResponse(BaseModel):
    id: UUID
    team_id: UUID
    user_id: UUID
    sent_by: str
    content: str
    metadata_log: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatUpdateRequest(BaseModel):
    content: str
