from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.models.lead import Lead
from app.schemas.emails import EmailCreate, EmailResponse
from app.schemas.common import ApiResponse
from app.services.emails_service import EmailService
from app.services.gmail_service import send_email_on_behalf_of_user
from sqlalchemy import select

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

    try:
        result = await db.execute(select(Lead).where(Lead.id == payload.lead_id))
        lead = result.scalar_one_or_none()
        if lead and lead.email:
            await send_email_on_behalf_of_user(
                db, current_user.id, lead.email, payload.subject, payload.body,
            )
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.warning(f"Gmail send failed for user {current_user.id}: {e}")

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