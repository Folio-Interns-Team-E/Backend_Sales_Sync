import logging

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_team_context, TeamContext
from app.models.user import User
from app.schemas.emails import EmailCreate, EmailUpdate, EmailResponse
from app.schemas.common import ApiResponse
from app.services.emails_service import EmailService
from app.services.gmail_service import send_email_on_behalf_of_user
from app.middleware.rate_limit import EMAIL_DRAFT, EMAIL_SEND, rate_limit
from app.services.plan_service import enforce_limit

router = APIRouter(prefix="/emails", tags=["emails"])
logger = logging.getLogger(__name__)


async def _deliver_email(
    service: EmailService,
    db: AsyncSession,
    email_id: UUID,
    team_id: UUID,
    user_id: UUID,
) -> EmailResponse:
    email, lead = await service.get_delivery_target(email_id, team_id)
    try:
        provider_message_id = await send_email_on_behalf_of_user(
            db,
            user_id,
            lead.email,
            email.subject,
            email.body,
        )
        if not provider_message_id:
            raise RuntimeError("Gmail did not return a message identifier")
    except Exception as exc:
        logger.exception("Gmail delivery failed for email %s", email_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail could not send this message. Reconnect Gmail and try again.",
        ) from exc
    return await service.mark_sent(email, lead, user_id, provider_message_id)


@router.get("/{email_id}", response_model=ApiResponse[EmailResponse])
async def get_email(
    email_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = EmailService(db)
    email = await service.get_email(email_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Email fetched successfully", data=email)


@router.patch("/{email_id}", response_model=ApiResponse[EmailResponse])
async def update_email(
    email_id: UUID,
    payload: EmailUpdate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = EmailService(db)
    email = await service.update_email(email_id, team_ctx.team_id, payload.subject, payload.body)
    return ApiResponse(success=True, message="Email updated successfully", data=email)


@router.get("/", response_model=ApiResponse[list[EmailResponse]])
async def list_emails(
    lead_id: UUID = Query(None),
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = EmailService(db)
    emails = await service.list_emails(team_ctx.team_id, lead_id)
    return ApiResponse(success=True, message="Emails fetched successfully", data=emails)


@router.post("/", response_model=ApiResponse[EmailResponse], status_code=201, dependencies=[Depends(rate_limit(EMAIL_SEND, "user", "team"))])
async def send_email(
    payload: EmailCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    team_ctx: TeamContext = Depends(get_team_context),
):
    await enforce_limit(db, team_ctx.team_id, "emails_monthly")
    service = EmailService(db)
    email = await service.draft_email(
        team_ctx.team_id,
        payload.lead_id,
        payload.subject,
        payload.body,
        {"tone": payload.tone, "sender_user_id": str(current_user.id)},
    )
    email = await _deliver_email(service, db, email.id, team_ctx.team_id, current_user.id)

    return ApiResponse(success=True, message="Email sent successfully", data=email)


@router.post(
    "/{email_id}/send",
    response_model=ApiResponse[EmailResponse],
    dependencies=[Depends(rate_limit(EMAIL_SEND, "user", "team"))],
)
async def send_draft_email(
    email_id: UUID,
    payload: EmailUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    team_ctx: TeamContext = Depends(get_team_context),
):
    await enforce_limit(db, team_ctx.team_id, "emails_monthly")
    service = EmailService(db)
    await service.update_email(email_id, team_ctx.team_id, payload.subject, payload.body)
    email = await _deliver_email(service, db, email_id, team_ctx.team_id, current_user.id)
    return ApiResponse(success=True, message="Email sent successfully", data=email)


@router.post("/draft", response_model=ApiResponse[EmailResponse], status_code=201, dependencies=[Depends(rate_limit(EMAIL_DRAFT, "user", "team"))])
async def draft_email(
    payload: EmailCreate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = EmailService(db)
    email = await service.draft_email(team_ctx.team_id, payload.lead_id, payload.subject, payload.body)
    return ApiResponse(success=True, message="Email drafted successfully", data=email)

@router.delete("/{email_id}", response_model=ApiResponse[dict])
async def delete_email(
    email_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = EmailService(db)
    await service.delete_email(email_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Email deleted", data={})
