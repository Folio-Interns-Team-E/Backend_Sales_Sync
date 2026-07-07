import logging
from typing import Optional
from uuid import UUID
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status
from app.models.knowledge_base import KnowledgeAsset
from app.models.team import Team
from app.models.team_member import TeamMember

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
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

    async def list_assets(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        query = select(KnowledgeAsset).where(KnowledgeAsset.team_id == team.id).order_by(desc(KnowledgeAsset.created_at))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_asset(self, asset_id: UUID, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id, KnowledgeAsset.team_id == team.id)
        )
        asset = result.scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge asset not found")
        return asset

    async def create_asset(self, user_id: UUID, title: str,
                            type: str = "Document",
                            company: Optional[str] = None,
                            asset_date: Optional[date] = None,
                            description: Optional[str] = None,
                            file_url: Optional[str] = None,
                            source_url: Optional[str] = None):
        team = await self._get_user_team(user_id)
        asset = KnowledgeAsset(
            team_id=team.id,
            title=title,
            type=type,
            company=company,
            date=asset_date,
            description=description,
            file_url=file_url,
            source_url=source_url,
            status="Indexed",
        )
        self.db.add(asset)
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    async def delete_asset(self, asset_id: UUID, user_id: UUID):
        asset = await self.get_asset(asset_id, user_id)
        await self.db.delete(asset)
        await self.db.commit()
