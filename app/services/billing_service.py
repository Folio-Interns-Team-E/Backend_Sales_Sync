import stripe
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.config import settings
from app.models.team import Team, SubscriptionStatus
from app.models.team_member import TeamMember

stripe.api_key = settings.stripe_secret_key


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_team(self, user_id: UUID) -> Team:
        """Get team associated with user"""
        result = await self.db.execute(
            select(TeamMember).where(TeamMember.user_id == user_id)
        )
        membership = result.scalars().first()
        if not membership:
            raise HTTPException(status_code=404, detail="Team not found for user")

        result = await self.db.execute(
            select(Team).where(Team.id == membership.team_id)
        )
        team = result.scalars().first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        return team

    async def create_checkout_session(self, user_id: UUID, tier: str) -> str:
        team = await self._get_user_team(user_id)
        
        price_map = {
            "growth": settings.stripe_growth_price,
            "enterprise": settings.stripe_enterprise_price,
        }
        
        price_id = price_map.get(tier)
        if not price_id:
            raise HTTPException(status_code=400, detail="Invalid tier")
        
        # create or get stripe customer
        if not team.stripe_customer_id:
            customer = stripe.Customer.create(
                metadata={"team_id": str(team.id)}
            )
            team.stripe_customer_id = customer.id
            await self.db.commit()
        
        # create checkout session
        session = stripe.checkout.Session.create(
            customer=team.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url="https://your-frontend.com/billing/success",
            cancel_url="https://your-frontend.com/billing/cancel",
            metadata={"team_id": str(team.id), "tier": tier}
        )
        
        return session.url

    async def cancel_subscription(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        
        if not team.stripe_subscription_id:
            raise HTTPException(status_code=400, detail="No active subscription")
        
        stripe.Subscription.modify(
            team.stripe_subscription_id,
            cancel_at_period_end=True
        )
        
        team.subscription_status = SubscriptionStatus.CANCELLED.value
        await self.db.commit()
        
        return {"message": "Subscription will cancel at end of billing period"}

    async def get_subscription_status(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        return {
            "tier": team.subscription_tier,
            "status": team.subscription_status,
            "ends_at": team.subscription_ends_at
        }
