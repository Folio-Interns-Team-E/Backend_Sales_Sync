import stripe
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.config import settings
from app.models.team import Team
from app.models.team_member import TeamMember
# Assuming Subscription and Invoice are in app.models.subscription
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier

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
        
        # Create stripe customer if they don't have one yet
        if not team.stripe_customer_id:
            # Using Stripe's async client to avoid blocking the event loop
            customer = await stripe.Customer.create_async(
                metadata={"team_id": str(team.id)},
                name=team.name # Nice to have in Stripe dashboard
            )
            team.stripe_customer_id = customer.id
            await self.db.commit()
        
        # Create checkout session
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

    async def cancel_subscription(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        
        # Query the latest active or trialing subscription for this team
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
        
        # Tell Stripe to cancel at period end
        await stripe.Subscription.modify_async(
            active_sub.stripe_subscription_id,
            cancel_at_period_end=True
        )
        
        # Crucial: DO NOT mark it as canceled in your DB immediately if you want them to keep access until the end of the month.
        # Stripe will fire a `customer.subscription.updated` webhook when this happens, which is where you should update your DB state.
        # But if you want to pessimistically flag it right now:
        active_sub.cancel_at_period_end = True
        await self.db.commit()
        
        return {"message": "Subscription will cancel at end of billing period"}

    async def get_subscription_status(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        
        # Fetch the most recent subscription
        result = await self.db.execute(
            select(Subscription)
            .where(Subscription.team_id == team.id)
            .order_by(Subscription.created_at.desc())
        )
        latest_sub = result.scalars().first()
        
        # Fallback if no subscription records exist (Free Tier fallback)
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