# File: backend/app/services/onboarding_service.py
# UPDATED VERSION - Replace existing file

import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ICP
from app.schemas.onboarding import ICPCreate, ICPUpdate
from app.services.grok_service import GrokService

logger = logging.getLogger(__name__)


class OnboardingService:
    """Service for onboarding and ICP management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_or_update_icp(
        self,
        user_id: UUID,
        product_description: str,
        target_market_description: str,
        goals: str,
        product_name: Optional[str] = None,
        company_description: Optional[str] = None,
        target_regions: Optional[list] = None
    ) -> ICP:
        """
        Create or update ICP by calling Grok to generate analysis.
        Now includes goals parameter for optimization.
        
        Args:
            user_id: User ID
            product_description: Product description
            target_market_description: Target market description
            goals: What should the sales copilot optimize for?
            product_name: Product name (optional)
            company_description: Company description (optional)
            target_regions: List of target regions (optional)
        
        Returns:
            ICP object with generated data
        """
        
        # Call Grok to generate ICP (now includes goals)
        logger.info(f"Generating ICP for user {user_id} via Grok with goals: {goals}")
        grok_result = await GrokService.generate_icp(
            product_description=product_description,
            target_market_description=target_market_description,
            goals=goals,
            product_name=product_name,
            company_description=company_description
        )
        
        # Check if user already has ICP
        existing_icp_result = await self.db.execute(
            select(ICP).where(ICP.user_id == user_id)
        )
        existing_icp = existing_icp_result.scalar_one_or_none()
        
        if existing_icp:
            # Update existing ICP
            logger.info(f"Updating existing ICP for user {user_id}")
            existing_icp.product_name = product_name
            existing_icp.product_description = product_description
            existing_icp.company_description = company_description
            existing_icp.target_market_description = target_market_description
            existing_icp.goals = goals  # NEW: Store goals
            existing_icp.target_regions = target_regions or []
            
            # Update with Grok results
            existing_icp.target_industries = grok_result.get("target_industries", [])
            existing_icp.company_size_range = grok_result.get("company_size_range")
            existing_icp.target_revenues = grok_result.get("target_revenues")
            existing_icp.decision_maker_titles = grok_result.get("decision_maker_titles", [])
            existing_icp.pain_points = grok_result.get("pain_points", [])
            existing_icp.key_characteristics = grok_result.get("key_characteristics", [])
            existing_icp.icp_summary = grok_result.get("icp_summary", [])  # NEW: Store summary for preview
            existing_icp.grok_analysis = grok_result.get("analysis")
            existing_icp.grok_full_response = grok_result.get("full_response")
            existing_icp.onboarding_completed = "completed"
            
            await self.db.commit()
            await self.db.refresh(existing_icp)
            return existing_icp
        
        else:
            # Create new ICP
            logger.info(f"Creating new ICP for user {user_id}")
            new_icp = ICP(
                user_id=user_id,
                product_name=product_name,
                product_description=product_description,
                company_description=company_description,
                target_market_description=target_market_description,
                goals=goals,  # NEW: Store goals
                target_regions=target_regions or [],
                target_industries=grok_result.get("target_industries", []),
                company_size_range=grok_result.get("company_size_range"),
                target_revenues=grok_result.get("target_revenues"),
                decision_maker_titles=grok_result.get("decision_maker_titles", []),
                pain_points=grok_result.get("pain_points", []),
                key_characteristics=grok_result.get("key_characteristics", []),
                icp_summary=grok_result.get("icp_summary", []),  # NEW: Store summary for preview
                grok_analysis=grok_result.get("analysis"),
                grok_full_response=grok_result.get("full_response"),
                onboarding_completed="completed"
            )
            
            self.db.add(new_icp)
            await self.db.commit()
            await self.db.refresh(new_icp)
            return new_icp

    async def get_icp(self, user_id: UUID) -> Optional[ICP]:
        """Get user's ICP"""
        result = await self.db.execute(
            select(ICP).where(ICP.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_icp(
        self,
        user_id: UUID,
        icp_update: ICPUpdate
    ) -> Optional[ICP]:
        """Update ICP with new user-provided data"""
        icp = await self.get_icp(user_id)
        
        if not icp:
            logger.warning(f"ICP not found for user {user_id}")
            return None
        
        # Update user-provided fields
        update_data = icp_update.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(icp, key, value)
        
        # Regenerate ICP with updated data
        product_desc = icp.product_description
        target_market = icp.target_market_description
        goals = icp.goals  # Use updated goals
        
        if not product_desc or not target_market or not goals:
            logger.error("Cannot regenerate ICP without product, target market, and goals descriptions")
            await self.db.commit()
            await self.db.refresh(icp)
            return icp
        
        # Call Grok with updated data
        grok_result = await GrokService.generate_icp(
            product_description=product_desc,
            target_market_description=target_market,
            goals=goals,
            product_name=icp.product_name,
            company_description=icp.company_description
        )
        
        # Update with new Grok results
        icp.target_industries = grok_result.get("target_industries", [])
        icp.company_size_range = grok_result.get("company_size_range")
        icp.target_revenues = grok_result.get("target_revenues")
        icp.decision_maker_titles = grok_result.get("decision_maker_titles", [])
        icp.pain_points = grok_result.get("pain_points", [])
        icp.key_characteristics = grok_result.get("key_characteristics", [])
        icp.icp_summary = grok_result.get("icp_summary", [])  # Update preview
        icp.grok_analysis = grok_result.get("analysis")
        icp.grok_full_response = grok_result.get("full_response")
        
        await self.db.commit()
        await self.db.refresh(icp)
        return icp

    async def delete_icp(self, user_id: UUID) -> bool:
        """Delete user's ICP"""
        icp = await self.get_icp(user_id)
        
        if not icp:
            return False
        
        await self.db.delete(icp)
        await self.db.commit()
        logger.info(f"Deleted ICP for user {user_id}")
        return True

    async def get_onboarding_status(self, user_id: UUID) -> dict:
        """Get user's onboarding status"""
        icp = await self.get_icp(user_id)
        
        if not icp:
            return {
                "status": "not_started",
                "completed": False,
                "icp": None
            }
        
        return {
            "status": icp.onboarding_completed,
            "completed": icp.onboarding_completed == "completed",
            "icp": icp
        }