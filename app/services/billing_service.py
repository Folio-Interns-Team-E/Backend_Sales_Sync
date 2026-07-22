import stripe
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.config import settings
from app.models.team import Team
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier

stripe.api_key = settings.stripe_secret_key


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_team(self, team_id: UUID) -> Team:
        result = await self.db.execute(select(Team).where(Team.id == team_id))
        team = result.scalars().first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        return team

    async def create_checkout_session(self, team_id: UUID, tier: str) -> str:
        team = await self._get_team(team_id)
        
        price_map = {
            "growth": settings.stripe_growth_price,
            "enterprise": settings.stripe_enterprise_price,
        }
        
        price_id = price_map.get(tier)
        if not price_id:
            raise HTTPException(status_code=400, detail="Invalid tier")
        
        if not team.stripe_customer_id:
            customer = await stripe.Customer.create_async(
                metadata={"team_id": str(team.id)},
                name=team.name
            )
            team.stripe_customer_id = customer.id
            await self.db.commit()
        
        session = await stripe.checkout.Session.create_async(
            customer=team.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url="http://localhost:8080/billing/success",
            cancel_url="http://localhost:8080/billing/cancel",
            metadata={"team_id": str(team.id), "tier": tier}
        )
        
        return session.url

    async def cancel_subscription(self, team_id: UUID):
        team = await self._get_team(team_id)
        
        result = await self.db.execute(
            select(Subscription)
            .where(
                Subscription.team_id == team.id,
                Subscription.status.in_([SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIALING.value])
            )
            .order_by(Subscription.created_at.desc())
        )
        active_sub = result.scalars().first()
        
        if not active_sub:
            raise HTTPException(status_code=400, detail="No active subscription found to cancel")
        
        await stripe.Subscription.modify_async(
            active_sub.stripe_subscription_id,
            cancel_at_period_end=True
        )
        
        active_sub.cancel_at_period_end = True
        await self.db.commit()
        
        return {"message": "Subscription will cancel at end of billing period"}

    async def get_subscription_status(self, team_id: UUID):
        team = await self._get_team(team_id)
        
        result = await self.db.execute(
            select(Subscription)
            .where(Subscription.team_id == team.id)
            .order_by(Subscription.created_at.desc())
        )
        latest_sub = result.scalars().first()
        
        if not latest_sub:
            return {
                "tier": SubscriptionTier.FREE.value,
                "status": SubscriptionStatus.ACTIVE.value,
                "ends_at": None,
                "cancel_at_period_end": False
            }
            
        return {
            "tier": latest_sub.tier,
            "status": latest_sub.status,
            "ends_at": latest_sub.current_period_end,
            "cancel_at_period_end": latest_sub.cancel_at_period_end
        }
