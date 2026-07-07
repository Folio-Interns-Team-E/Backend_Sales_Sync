from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.emails import EmailCreate, EmailResponse
from app.schemas.common import ApiResponse
from app.services.emails_service import EmailService

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("/", response_model=ApiResponse[list[EmailResponse]])
async def list_emails(
    lead_id: UUID = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EmailService(db)
    emails = await service.list_emails(current_user.id, lead_id)
    return ApiResponse(success=True, message="Emails fetched successfully", data=emails)


@router.post("/", response_model=ApiResponse[EmailResponse], status_code=201)
async def send_email(
    payload: EmailCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EmailService(db)
    email = await service.create_email(current_user.id, payload.lead_id, payload.subject, payload.body, payload.tone)
    return ApiResponse(success=True, message="Email sent successfully", data=email)


@router.post("/draft", response_model=ApiResponse[EmailResponse], status_code=201)
async def draft_email(
    payload: EmailCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EmailService(db)
    email = await service.draft_email(current_user.id, payload.lead_id, payload.subject, payload.body)
    return ApiResponse(success=True, message="Email drafted successfully", data=email)
