from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.emails import EmailCreate, EmailUpdate, EmailResponse
from app.schemas.common import ApiResponse
from app.services.emails_service import EmailService
from app.services.gmail_service import send_email_in_background

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("/{email_id}", response_model=ApiResponse[EmailResponse])
async def get_email(
    email_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EmailService(db)
    email = await service.get_email(email_id, current_user.id)
    return ApiResponse(success=True, message="Email fetched successfully", data=email)


@router.patch("/{email_id}", response_model=ApiResponse[EmailResponse])
async def update_email(
    email_id: UUID,
    payload: EmailUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EmailService(db)
    email = await service.update_email(email_id, current_user.id, payload.subject, payload.body)
    return ApiResponse(success=True, message="Email updated successfully", data=email)


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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EmailService(db)
    email = await service.create_email(current_user.id, payload.lead_id, payload.subject, payload.body, payload.tone)

    background_tasks.add_task(
        send_email_in_background,
        current_user.id,
        payload.lead_id,
        payload.subject,
        payload.body,
    )

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

@router.delete("/{email_id}", response_model=ApiResponse[dict])
async def delete_email(
    email_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EmailService(db)
    await service.delete_email(email_id, current_user.id)
    return ApiResponse(success=True, message="Email deleted", data={})