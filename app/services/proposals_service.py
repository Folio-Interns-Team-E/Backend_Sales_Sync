import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_
from fastapi import HTTPException, status
from app.models.proposal import Proposal, ProposalTemplate, ProposalStatus, ProposalOutcome
from app.models.lead import Lead
from app.core.s3 import generate_presigned_url, upload_to_s3 as s3_upload

logger = logging.getLogger(__name__)


class ProposalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_proposals(self, team_id: UUID):
        query = (
            select(Proposal)
            .outerjoin(Lead, Proposal.lead_id == Lead.id)
            .where(
                or_(
                    Lead.team_id == team_id,
                    Proposal.lead_id.is_(None)
                )
            )
            .order_by(desc(Proposal.updated_at))
        )
        result = await self.db.execute(query)
        proposals = result.scalars().all()
        from app.schemas.proposals import ProposalResponse
        data = [ProposalResponse.model_validate(p).model_dump(mode="json") for p in proposals]
        return data

    async def get_proposal(self, proposal_id: UUID, team_id: UUID):
        result = await self.db.execute(
            select(Proposal)
            .outerjoin(Lead, Proposal.lead_id == Lead.id)
            .where(
                Proposal.id == proposal_id,
                or_(
                    Lead.team_id == team_id,
                    Proposal.lead_id.is_(None)
                )
            )
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
        if proposal.file_url and "amazonaws.com" in proposal.file_url:
            proposal.presigned_url = generate_presigned_url(proposal.file_url)
        return proposal

    async def create_proposal(self, team_id: UUID, file_url: str,
                               lead_id: Optional[UUID] = None,
                               file_type: Optional[str] = None,
                               file_size: Optional[int] = None,
                               template_id: Optional[UUID] = None,
                               ai_metadata: Optional[dict] = None):
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

    async def update_proposal(self, proposal_id: UUID, team_id: UUID,
                               file_url: Optional[str] = None,
                               file_type: Optional[str] = None,
                               file_size: Optional[int] = None,
                               lead_id: Optional[UUID] = None,
                               template_id: Optional[UUID] = None,
                               ai_metadata: Optional[dict] = None):
        proposal = await self.get_proposal(proposal_id, team_id)
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

    def _attach_template_presigned(self, template: ProposalTemplate):
        if template.file_url and "amazonaws.com" in template.file_url:
            template.presigned_url = generate_presigned_url(template.file_url)

    async def get_template(self, team_id: UUID):
        result = await self.db.execute(
            select(ProposalTemplate).where(ProposalTemplate.team_id == team_id)
        )
        template = result.scalar_one_or_none()
        if template:
            self._attach_template_presigned(template)
        return template

    async def upsert_template(self, team_id: UUID,
                               template_name: Optional[str] = None,
                               file_url: Optional[str] = None,
                               file_type: Optional[str] = None,
                               file_size: Optional[int] = None):
        result = await self.db.execute(
            select(ProposalTemplate).where(ProposalTemplate.team_id == team_id)
        )
        template = result.scalar_one_or_none()
        if not template:
            template = ProposalTemplate(
                team_id=team_id,
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
        self._attach_template_presigned(template)
        return template

    async def upload_template(
        self,
        team_id: UUID,
        user_id: UUID,
        template_name: str,
        file_bytes: bytes,
        filename: str,
        content_type: str,
    ):
        file_url = await s3_upload(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            prefix="proposal-templates",
            user_id=str(user_id),
        )

        file_type = content_type.split("/")[-1] if content_type else None
        file_size = len(file_bytes)

        return await self.upsert_template(
            team_id,
            template_name=template_name,
            file_url=file_url,
            file_type=file_type,
            file_size=file_size,
        )

    async def delete_proposal(self, proposal_id: UUID, team_id: UUID):
        proposal = await self.get_proposal(proposal_id, team_id)
        await self.db.delete(proposal)
        await self.db.commit()

    async def update_status(self, proposal_id: UUID, team_id: UUID, new_status: str):
        proposal = await self.get_proposal(proposal_id, team_id)

        if new_status not in [s.value for s in ProposalStatus]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status value"
            )

        proposal.status = new_status
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    async def update_outcome(self, proposal_id: UUID, team_id: UUID, outcome: str):
        proposal = await self.get_proposal(proposal_id, team_id)

        if outcome not in [o.value for o in ProposalOutcome]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid outcome value"
            )

        proposal.outcome = outcome

        if outcome == ProposalOutcome.WON.value:
            proposal.status = ProposalStatus.ACCEPTED.value
        elif outcome == ProposalOutcome.LOST.value:
            proposal.status = ProposalStatus.REJECTED.value

        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal
