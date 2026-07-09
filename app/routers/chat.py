from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse, ChatMessageResponse, ChatUpdateRequest
from app.schemas.common import ApiResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/", response_model=ApiResponse[list[ChatMessageResponse]])
async def list_messages(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    messages = await service.list_messages(current_user.id)
    return ApiResponse(success=True, message="Messages fetched successfully", data=messages)


@router.get("/{message_id}", response_model=ApiResponse[ChatMessageResponse])
async def get_message(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    message = await service.get_message(message_id, current_user.id)
    return ApiResponse(success=True, message="Message fetched successfully", data=message)


@router.patch("/{message_id}", response_model=ApiResponse[ChatMessageResponse])
async def update_message(
    message_id: UUID,
    payload: ChatUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    message = await service.update_message(message_id, current_user.id, payload.content)
    return ApiResponse(success=True, message="Message updated successfully", data=message)


@router.delete("/{message_id}", response_model=ApiResponse[dict])
async def delete_message(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    await service.delete_message(message_id, current_user.id)
    return ApiResponse(success=True, message="Message deleted", data={})


@router.post("/", response_model=ApiResponse[ChatResponse])
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    try:
        reply = await service.send_message(current_user.id, payload.message)
        return ApiResponse(
            success=True,
            message="Chat response generated",
            data=ChatResponse(reply=reply),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat failed: {str(e)}",
        )
