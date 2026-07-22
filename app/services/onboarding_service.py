import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.models.team import Team
from app.models.team_member import TeamMember

logger = logging.getLogger(__name__)


class OnboardingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_team(self, team_id: UUID) -> Team:
        result = await self.db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        return team

    async def submit_onboarding(self, team_id: UUID, product_name: str | None,
                                 product_description: str, target_customer: str,
                                 goals: str) -> str:
        team = await self._get_team(team_id)
        team.icp = product_description
        await self.db.commit()
        return product_description

    async def get_onboarding(self, team_id: UUID) -> dict:
        team = await self._get_team(team_id)
        return {
            "icp": team.icp or "",
            "completed": team.icp is not None and team.icp != "",
        }

    async def update_onboarding(self, team_id: UUID,
                                 product_name: str | None = None,
                                 product_description: str | None = None,
                                 target_customer: str | None = None,
                                 goals: str | None = None) -> str:
        team = await self._get_team(team_id)
        if not team.icp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No ICP found")
        if product_description is not None:
            team.icp = product_description
        await self.db.commit()
        return team.icp

    async def delete_onboarding(self, team_id: UUID) -> None:
        team = await self._get_team(team_id)
        team.icp = None
        await self.db.commit()
