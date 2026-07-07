import logging
from typing import Optional
from uuid import UUID
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from app.models.team import Team
from app.models.team_member import TeamMember

logger = logging.getLogger(__name__)


class OnboardingService:
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

    async def submit_onboarding(self, user_id: UUID, product_name: Optional[str],
                                 product_description: str, target_customer: str,
                                 goals: str) -> str:
        team = await self._get_user_team(user_id)

        icp_text = json.dumps({
            "productName": product_name or "",
            "productDescription": product_description,
            "targetCustomer": target_customer,
            "goals": goals,
        })

        team.icp = icp_text
        await self.db.commit()
        return icp_text

    async def get_onboarding(self, user_id: UUID) -> dict:
        team = await self._get_user_team(user_id)
        return {
            "icp": team.icp or "",
            "completed": team.icp is not None and team.icp != "",
        }

    async def update_onboarding(self, user_id: UUID,
                                 product_name: Optional[str] = None,
                                 product_description: Optional[str] = None,
                                 target_customer: Optional[str] = None,
                                 goals: Optional[str] = None) -> str:
        team = await self._get_user_team(user_id)
        if not team.icp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No ICP found")

        current = json.loads(team.icp)
        if product_name is not None:
            current["productName"] = product_name
        if product_description is not None:
            current["productDescription"] = product_description
        if target_customer is not None:
            current["targetCustomer"] = target_customer
        if goals is not None:
            current["goals"] = goals

        team.icp = json.dumps(current)
        await self.db.commit()
        return team.icp
