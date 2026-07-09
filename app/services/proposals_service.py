import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status
from app.models.proposal import Proposal, ProposalTemplate, ProposalStatus, ProposalOutcome
from app.models.lead import Lead
from app.models.team import Team
from app.models.team_member import TeamMember

logger = logging.getLogger(__name__)


class ProposalService:
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
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        return team

    async def list_proposals(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        query = (
            select(Proposal)
            .join(Lead, Proposal.lead_id == Lead.id)
            .where(Lead.team_id == team.id)
            .order_by(desc(Proposal.updated_at))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_proposal(self, proposal_id: UUID, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(Proposal)
            .join(Lead, Proposal.lead_id == Lead.id)
            .where(Proposal.id == proposal_id, Lead.team_id == team.id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
        return proposal

    async def create_proposal(self, user_id: UUID, file_url: str,
                               lead_id: Optional[UUID] = None,
                               file_type: Optional[str] = None,
                               file_size: Optional[int] = None,
                               template_id: Optional[UUID] = None,
                               ai_metadata: Optional[dict] = None):
        team = await self._get_user_team(user_id)
        proposal = Proposal(
            lead_id=lead_id,
            template_id=template_id,
            file_url=file_url,
            file_type=file_type,
            file_size=file_size,
            ai_metadata=ai_metadata or {},
            status=ProposalStatus.DRAFT.value,
            outcome=ProposalOutcome.OPEN.value,
        )
        self.db.add(proposal)
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    async def update_proposal(self, proposal_id: UUID, user_id: UUID,
                               file_url: Optional[str] = None,
                               file_type: Optional[str] = None,
                               file_size: Optional[int] = None,
                               lead_id: Optional[UUID] = None,
                               template_id: Optional[UUID] = None,
                               ai_metadata: Optional[dict] = None):
        proposal = await self.get_proposal(proposal_id, user_id)
        if file_url is not None:
            proposal.file_url = file_url
        if file_type is not None:
            proposal.file_type = file_type
        if file_size is not None:
            proposal.file_size = file_size
        if lead_id is not None:
            proposal.lead_id = lead_id
        if template_id is not None:
            proposal.template_id = template_id
        if ai_metadata is not None:
            proposal.ai_metadata = ai_metadata
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    async def get_template(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(ProposalTemplate).where(ProposalTemplate.team_id == team.id)
        )
        return result.scalar_one_or_none()

    async def upsert_template(self, user_id: UUID,
                               template_name: Optional[str] = None,
                               file_url: Optional[str] = None,
                               file_type: Optional[str] = None,
                               file_size: Optional[int] = None):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(ProposalTemplate).where(ProposalTemplate.team_id == team.id)
        )
        template = result.scalar_one_or_none()
        if not template:
            template = ProposalTemplate(
                team_id=team.id,
                template_name=template_name or "Default",
                file_url=file_url or "",
                file_type=file_type,
                file_size=file_size,
            )
            self.db.add(template)
        else:
            if template_name is not None:
                template.template_name = template_name
            if file_url is not None:
                template.file_url = file_url
            if file_type is not None:
                template.file_type = file_type
            if file_size is not None:
                template.file_size = file_size
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def delete_proposal(self, proposal_id: UUID, user_id: UUID):
        proposal = await self.get_proposal(proposal_id, user_id)
        await self.db.delete(proposal)
        await self.db.commit()

    async def update_status(self, proposal_id: UUID, user_id: UUID, new_status: str):
        proposal = await self.get_proposal(proposal_id, user_id)
        
        if new_status not in [s.value for s in ProposalStatus]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status value"
            )
        
        proposal.status = new_status
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal


    async def update_outcome(self, proposal_id: UUID, user_id: UUID, outcome: str):
        proposal = await self.get_proposal(proposal_id, user_id)
        
        if outcome not in [o.value for o in ProposalOutcome]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid outcome value"
            )
        
        proposal.outcome = outcome
        
        # auto-sync status with outcome
        if outcome == ProposalOutcome.WON.value:
            proposal.status = ProposalStatus.ACCEPTED.value
        elif outcome == ProposalOutcome.LOST.value:
            proposal.status = ProposalStatus.REJECTED.value
        
        # placeholder: trigger KB update here
        # await kb_service.store_proposal_outcome(proposal)
        
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal
