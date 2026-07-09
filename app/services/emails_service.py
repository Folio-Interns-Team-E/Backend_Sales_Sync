import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status
from app.models.email import Email, EmailStatus
from app.models.lead import Lead
from app.models.team import Team
from app.models.team_member import TeamMember

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_team(self, user_id: UUID) -> Team:
        result = await self.db.execute(
            select(TeamMember).where(TeamMember.user_id == user_id)
        )
        membership = result.scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no team")
        result = await self.db.execute(select(Team).where(Team.id == membership.team_id))
        team = result.scalar_one_or_none()
        return team

    async def list_emails(self, user_id: UUID, lead_id: UUID):
        team = await self._get_user_team(user_id)
        query = select(Email).where(Email.lead_id == lead_id)
        query = query.order_by(desc(Email.sent_at))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def create_email(self, user_id: UUID, lead_id: UUID, subject: str,
                           body: str, tone: str = "Professional"):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.team_id == team.id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

        email = Email(
           
            lead_id=lead_id,
            subject=subject,
            body=body,
            status=EmailStatus.SENT,
            ai_metadata={"tone": tone},
        )
        self.db.add(email)

        lead.status = "Sent"
        await self.db.commit()
        await self.db.refresh(email)
        return email

    async def draft_email(self, user_id: UUID, lead_id: UUID, subject: str, body: str):
        team = await self._get_user_team(user_id)
        email = Email(
          
            lead_id=lead_id,
            subject=subject,
            body=body,
            status=EmailStatus.DRAFT,
        )
        self.db.add(email)

        result = await self.db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.team_id == team.id)
        )
        lead = result.scalar_one_or_none()
        if lead:
            lead.status = "Drafted"
        await self.db.commit()
        await self.db.refresh(email)
        return email
    
    async def delete_email(self, email_id: UUID, user_id: UUID):
        team = await self._get_user_team(user_id)
        
        # fetch email and verify it belongs to this team via lead
        result = await self.db.execute(
            select(Email)
            .join(Lead, Email.lead_id == Lead.id)
            .where(Email.id == email_id, Lead.team_id == team.id)
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
