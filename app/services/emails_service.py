import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status
from app.models.email import Email, EmailStatus
from app.models.lead import Lead
from app.schemas.emails import EmailResponse

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_email(self, email_id: UUID, team_id: UUID):
        result = await self.db.execute(
            select(Email)
            .join(Lead, Email.lead_id == Lead.id)
            .where(Email.id == email_id, Lead.team_id == team_id)
        )
        email = result.scalar_one_or_none()
        if not email:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
        return email

    async def list_emails(self, team_id: UUID, lead_id: UUID):
        result = await self.db.execute(
            select(Email)
            .join(Lead, Email.lead_id == Lead.id)
            .where(Email.lead_id == lead_id, Lead.team_id == team_id)
            .order_by(desc(Email.sent_at))
        )
        emails = result.scalars().all()
        data = [EmailResponse.model_validate(e).model_dump(mode="json") for e in emails]
        return data

    async def draft_email(
        self,
        team_id: UUID,
        lead_id: UUID,
        subject: str,
        body: str,
        ai_metadata: dict | None = None,
    ):
        result = await self.db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.team_id == team_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

        email = Email(
            lead_id=lead_id,
            subject=subject,
            body=body,
            status=EmailStatus.DRAFT,
            ai_metadata=ai_metadata or {},
        )
        self.db.add(email)
        lead.status = "Drafted"
        await self.db.commit()
        await self.db.refresh(email)
        return email

    async def get_delivery_target(self, email_id: UUID, team_id: UUID) -> tuple[Email, Lead]:
        result = await self.db.execute(
            select(Email, Lead)
            .join(Lead, Email.lead_id == Lead.id)
            .where(Email.id == email_id, Lead.team_id == team_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
        email, lead = row
        if email.status == EmailStatus.SENT:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email was already sent")
        if not lead.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lead does not have an email address",
            )
        return email, lead

    async def mark_sent(
        self,
        email: Email,
        lead: Lead,
        sender_id: UUID,
        provider_message_id: str,
    ) -> Email:
        email.status = EmailStatus.SENT
        email.sent_at = datetime.now(timezone.utc)
        email.ai_metadata = {
            **(email.ai_metadata or {}),
            "sender_user_id": str(sender_id),
            "provider_message_id": provider_message_id,
        }
        lead.status = "Sent"
        await self.db.commit()
        await self.db.refresh(email)
        return email

    async def update_email(self, email_id: UUID, team_id: UUID,
                            subject: str | None = None,
                            body: str | None = None):
        email = await self.get_email(email_id, team_id)
        if email.status == EmailStatus.SENT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update a sent email"
            )
        if subject is not None:
            email.subject = subject
        if body is not None:
            email.body = body
        await self.db.commit()
        await self.db.refresh(email)
        return email

    async def delete_email(self, email_id: UUID, team_id: UUID):
        result = await self.db.execute(
            select(Email)
            .join(Lead, Email.lead_id == Lead.id)
            .where(Email.id == email_id, Lead.team_id == team_id)
        )
        email = result.scalar_one_or_none()

        if not email:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email not found"
            )

        if email.status == EmailStatus.SENT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete a sent email"
            )

        await self.db.delete(email)
        await self.db.commit()
