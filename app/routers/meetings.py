from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.meetings import MeetingCreate, MeetingUpdate, MeetingResponse
from app.schemas.common import ApiResponse
from app.services.meetings_service import MeetingService

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("/", response_model=ApiResponse[list[MeetingResponse]])
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MeetingService(db)
    meetings = await service.list_meetings(current_user.id)
    return ApiResponse(success=True, message="Meetings fetched successfully", data=meetings)


@router.get("/{meeting_id}", response_model=ApiResponse[MeetingResponse])
async def get_meeting(
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MeetingService(db)
    meeting = await service.get_meeting(meeting_id, current_user.id)
    return ApiResponse(success=True, message="Meeting fetched successfully", data=meeting)


@router.post("/", response_model=ApiResponse[MeetingResponse], status_code=201)
async def create_meeting(
    payload: MeetingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MeetingService(db)
    meeting = await service.create_meeting(
        current_user.id, payload.lead_id,
        payload.date, payload.time, payload.timezone,
        payload.calendar_event_id, payload.agenda, payload.notes,
    )
    return ApiResponse(success=True, message="Meeting created successfully", data=meeting)


@router.patch("/{meeting_id}", response_model=ApiResponse[MeetingResponse])
async def update_meeting(
    meeting_id: UUID,
    payload: MeetingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MeetingService(db)
    meeting = await service.update_meeting(
        meeting_id, current_user.id, payload.status,
        payload.notes, payload.agenda, payload.date,
        payload.time, payload.timezone, payload.calendar_event_id,
    )
    return ApiResponse(success=True, message="Meeting updated successfully", data=meeting)


@router.delete("/{meeting_id}", response_model=ApiResponse[dict])
async def delete_meeting(
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MeetingService(db)
    await service.delete_meeting(meeting_id, current_user.id)
    return ApiResponse(success=True, message="Meeting deleted", data={})
