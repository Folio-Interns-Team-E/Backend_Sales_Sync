from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.lead import Lead
from app.models.opportunity import Opportunity, OpportunityStage
from app.models.team_member import MemberRole, TeamMember
from app.models.user import User
from app.schemas.opportunities import OpportunityCreate, OpportunitySummary, OpportunityUpdate


OPEN_STAGES = [
    OpportunityStage.PROSPECTING.value,
    OpportunityStage.QUALIFICATION.value,
    OpportunityStage.PROPOSAL.value,
    OpportunityStage.NEGOTIATION.value,
]


class OpportunityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _visible(self, query, user_id: UUID, role: MemberRole):
        if role == MemberRole.rep:
            return query.where(or_(Opportunity.owner_id == user_id, Opportunity.owner_id.is_(None)))
        return query

    async def _validate_relations(self, team_id: UUID, lead_id: Optional[UUID], owner_id: Optional[UUID]):
        if lead_id:
            lead = await self.db.scalar(select(Lead).where(Lead.id == lead_id, Lead.team_id == team_id))
            if not lead:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lead does not belong to this workspace")
        if owner_id:
            member = await self.db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == owner_id))
            if not member:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Owner is not a workspace member")

    async def list(self, team_id: UUID, user_id: UUID, role: MemberRole, stage: Optional[str] = None):
        query = select(Opportunity).where(Opportunity.team_id == team_id).options(selectinload(Opportunity.owner)).order_by(Opportunity.updated_at.desc())
        query = self._visible(query, user_id, role)
        if stage:
            query = query.where(Opportunity.stage == stage)
        return list((await self.db.execute(query)).scalars().all())

    async def get(self, opportunity_id: UUID, team_id: UUID, user_id: UUID, role: MemberRole):
        query = select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.team_id == team_id).options(selectinload(Opportunity.owner))
        opportunity = (await self.db.execute(self._visible(query, user_id, role))).scalar_one_or_none()
        if not opportunity:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")
        return opportunity

    async def create(self, team_id: UUID, user_id: UUID, role: MemberRole, payload: OpportunityCreate):
        owner_id = payload.owner_id or user_id
        if role == MemberRole.rep and owner_id != user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sales reps can only assign opportunities to themselves")
        await self._validate_relations(team_id, payload.lead_id, owner_id)
        data = payload.model_dump()
        data["stage"] = payload.stage.value
        data["owner_id"] = owner_id
        opportunity = Opportunity(team_id=team_id, **data)
        self.db.add(opportunity)
        await self.db.commit()
        return await self.get(opportunity.id, team_id, user_id, role)

    async def update(self, opportunity_id: UUID, team_id: UUID, user_id: UUID, role: MemberRole, payload: OpportunityUpdate):
        opportunity = await self.get(opportunity_id, team_id, user_id, role)
        changes = payload.model_dump(exclude_unset=True)
        if role == MemberRole.rep and changes.get("owner_id", user_id) != user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sales reps cannot reassign opportunities")
        await self._validate_relations(team_id, changes.get("lead_id"), changes.get("owner_id"))
        if "stage" in changes and changes["stage"] is not None:
            changes["stage"] = changes["stage"].value
        if changes.get("stage") == OpportunityStage.CLOSED_WON.value:
            changes["probability"] = 100
            changes["loss_reason"] = None
        elif changes.get("stage") == OpportunityStage.CLOSED_LOST.value:
            changes["probability"] = 0
        elif changes.get("stage"):
            changes["loss_reason"] = None
        for key, value in changes.items():
            setattr(opportunity, key, value)
        await self.db.commit()
        return await self.get(opportunity.id, team_id, user_id, role)

    async def delete(self, opportunity_id: UUID, team_id: UUID, user_id: UUID, role: MemberRole):
        opportunity = await self.get(opportunity_id, team_id, user_id, role)
        await self.db.delete(opportunity)
        await self.db.commit()

    async def summary(self, team_id: UUID, user_id: UUID, role: MemberRole):
        records = await self.list(team_id, user_id, role)
        open_records = [item for item in records if item.stage in OPEN_STAGES]
        won_records = [item for item in records if item.stage == OpportunityStage.CLOSED_WON.value]
        lost_records = [item for item in records if item.stage == OpportunityStage.CLOSED_LOST.value]
        return OpportunitySummary(
            total_count=len(records), open_count=len(open_records), won_count=len(won_records), lost_count=len(lost_records),
            pipeline_value=sum((item.amount for item in open_records), Decimal("0")),
            weighted_value=sum((item.amount * Decimal(item.probability) / Decimal(100) for item in open_records), Decimal("0")),
            won_value=sum((item.amount for item in won_records), Decimal("0")),
        )


def serialize_opportunity(opportunity: Opportunity):
    opportunity.owner_name = opportunity.owner.full_name if opportunity.owner else None
    return opportunity
