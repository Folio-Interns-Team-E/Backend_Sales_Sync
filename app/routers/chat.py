from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_team_context, TeamContext
from app.models.user import User
from app.schemas.chat import (
    ChatCreateRequest,
    ChatResponse,
    ChatNameUpdateRequest,
    ChatRequest,
    ChatSendResponse,
    ChatMessageResponse,
    ChatUpdateRequest,
)
from app.schemas.common import ApiResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


# =====================================================
# CHAT CRUD
# =====================================================
@router.get("/chats", response_model=ApiResponse[list[ChatResponse]])
async def list_chats(
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    chats = await service.list_chats(team_ctx.team_id)
    return ApiResponse(success=True, message="Chats fetched", data=chats)


@router.post("/chats", response_model=ApiResponse[ChatResponse])
async def create_chat(
    payload: ChatCreateRequest,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    chat = await service.create_chat(team_ctx.team_id, payload.chat_name)
    return ApiResponse(success=True, message="Chat created", data=chat)


@router.patch("/chats/{chat_id}", response_model=ApiResponse[ChatResponse])
async def rename_chat(
    chat_id: UUID,
    payload: ChatNameUpdateRequest,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    chat = await service.rename_chat(chat_id, team_ctx.team_id, payload.chat_name)
    return ApiResponse(success=True, message="Chat renamed", data=chat)


@router.delete("/chats/{chat_id}", response_model=ApiResponse[dict])
async def delete_chat(
    chat_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    await service.delete_chat(chat_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Chat deleted", data={})


# =====================================================
# MESSAGES (scoped to chat_id)
# =====================================================
@router.get("/chats/{chat_id}/messages", response_model=ApiResponse[list[ChatMessageResponse]])
async def list_messages(
    chat_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    messages = await service.list_messages(chat_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Messages fetched", data=messages)


@router.post("/chats/{chat_id}/messages", response_model=ApiResponse[ChatSendResponse])
async def chat(
    chat_id: UUID,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    try:
        reply = await service.send_message(
            current_user.id, team_ctx.team_id, chat_id, payload.message
        )
        return ApiResponse(
            success=True,
            message="Chat response generated",
            data=ChatSendResponse(reply=reply),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat failed: {str(e)}",
        )


@router.patch("/messages/{message_id}", response_model=ApiResponse[ChatMessageResponse])
async def update_message(
    message_id: UUID,
    payload: ChatUpdateRequest,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    message = await service.update_message(message_id, team_ctx.team_id, payload.content)
    return ApiResponse(success=True, message="Message updated", data=message)


@router.delete("/messages/{message_id}", response_model=ApiResponse[dict])
async def delete_message(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ChatService(db)
    await service.delete_message(message_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Message deleted", data={})
