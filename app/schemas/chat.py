from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class ChatCreateRequest(BaseModel):
    chat_name: str = "New Chat"


class ChatResponse(BaseModel):
    id: UUID
    team_id: UUID
    chat_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    id: UUID
    chat_id: UUID
    team_id: UUID
    user_id: UUID
    user_name: str
    sent_by: str
    content: str
    metadata_log: dict
    created_at: datetime


class ChatRequest(BaseModel):
    message: str


class ChatSendResponse(BaseModel):
    reply: str


class ChatUpdateRequest(BaseModel):
    content: str


class ChatNameUpdateRequest(BaseModel):
    chat_name: str
