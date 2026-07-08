import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status
from app.models.proposal import Proposal, ProposalTemplate, ProposalStatus, ProposalOutcome
from app.models.proposal import ProposalRevision
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
        return team

    async def list_proposals(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        query = select(Proposal).where(Proposal.team_id == team.id).order_by(desc(Proposal.updated_at))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_proposal(self, proposal_id: UUID, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(Proposal).where(Proposal.id == proposal_id, Proposal.team_id == team.id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
        return proposal

    async def create_proposal(self, user_id: UUID, company: str,
                               title: str = "New Proposal",
                               summary: Optional[str] = None,
                               value: Optional[float] = None,
                               lead_id: Optional[UUID] = None):
        team = await self._get_user_team(user_id)
        proposal = Proposal(
            team_id=team.id,
            lead_id=lead_id,
            company=company,
            title=title,
            summary=summary,
            value=value,
            status=ProposalStatus.DRAFT.value,
            outcome=ProposalOutcome.OPEN.value,
        )
        self.db.add(proposal)
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    async def update_proposal(self, proposal_id: UUID, user_id: UUID,
                               title: Optional[str] = None,
                               summary: Optional[str] = None,
                               value: Optional[float] = None):
        proposal = await self.get_proposal(proposal_id, user_id)
        if title is not None:
            proposal.title = title
        if summary is not None:
            proposal.summary = summary
        if value is not None:
            proposal.value = value
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    #SPLIT INTO UPDATE OUTCOME AND UPDATE STATUS

    async def add_revision(self, proposal_id: UUID, user_id: UUID,
                            title: str, summary: str,
                            value: Optional[float] = None,
                            note: str = ""):
        proposal = await self.get_proposal(proposal_id, user_id)
        revision_count = len(proposal.revisions or [])
        revision = ProposalRevision(
            proposal_id=proposal_id,
            revision_num=revision_count + 1,
            title=title,
            summary=summary,
            value=value,
            note=note,
        )
        proposal.title = title
        proposal.summary = summary
        if value is not None:
            proposal.value = value
        self.db.add(revision)
        await self.db.commit()
        await self.db.refresh(revision)
        return revision

    async def get_template(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(ProposalTemplate).where(ProposalTemplate.team_id == team.id)
        )
        return result.scalar_one_or_none()

    async def upsert_template(self, user_id: UUID, template_name: Optional[str] = None,
                               company_name: Optional[str] = None,
                               logo_url: Optional[str] = None,
                               sections: Optional[list[dict]] = None):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(ProposalTemplate).where(ProposalTemplate.team_id == team.id)
        )
        template = result.scalar_one_or_none()
        if not template:
            template = ProposalTemplate(
                team_id=team.id,
                template_name=template_name or "Default",
                company_name=company_name,
                logo_url=logo_url,
                sections=sections or [],
            )
            self.db.add(template)
        else:
            if template_name is not None:
                template.template_name = template_name
            if company_name is not None:
                template.company_name = company_name
            if logo_url is not None:
                template.logo_url = logo_url
            if sections is not None:
                template.sections = sections
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def delete_proposal(self, proposal_id: UUID, user_id: UUID):
        proposal = await self.get_proposal(proposal_id, user_id)
        await self.db.delete(proposal)
        await self.db.commit()

    async def update_status(self, proposal_id: UUID, user_id: UUID, status: str):
        proposal = await self.get_proposal(proposal_id, user_id)
        
        if status not in [s.value for s in ProposalStatus]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status value"
            )
        
        proposal.status = status
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
