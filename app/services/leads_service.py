import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from app.models.lead import Lead, LeadStatus
from app.models.team import Team
from app.models.team_member import TeamMember

logger = logging.getLogger(__name__)


class LeadService:
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

    async def list_leads(self, user_id: UUID, status_filter: Optional[str] = None):
        team = await self._get_user_team(user_id)
        query = select(Lead).where(Lead.team_id == team.id)
        if status_filter:
            query = query.where(Lead.status == status_filter)
        query = query.order_by(desc(Lead.created_at))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_lead(self, lead_id: UUID, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.team_id == team.id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
        return lead

    async def create_lead(self, user_id: UUID, name: str, company: Optional[str] = None,
                          title: Optional[str] = None, email: Optional[str] = None,
                          source: Optional[str] = None):
        team = await self._get_user_team(user_id)
        lead = Lead(
            team_id=team.id,
            name=name,
            company_name=company,
            job_title=title,
            email=email,
            source=source,
        )
        self.db.add(lead)
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def update_lead_status(self, lead_id: UUID, user_id: UUID,
                                  status: str, score: Optional[int] = None,
                                  reasoning: Optional[str] = None):
        lead = await self.get_lead(lead_id, user_id)
        lead.status = status
        if score is not None:
            lead.score = score
        if reasoning is not None:
            lead.ai_context_data = {**(lead.ai_context_data or {}), "reasoning": reasoning}
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def discard_lead(self, lead_id: UUID, user_id: UUID):
        return await self.update_lead_status(lead_id, user_id, "Discarded")

    async def qualify_lead(self, lead_id: UUID, user_id: UUID):
        return await self.update_lead_status(lead_id, user_id, "Qualified")

    async def delete_lead(self, lead_id: UUID, user_id: UUID):
        lead = await self.get_lead(lead_id, user_id)
        await self.db.delete(lead)
        await self.db.commit()
