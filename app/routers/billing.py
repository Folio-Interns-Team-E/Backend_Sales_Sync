from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import stripe

from app.database import get_db
from app.config import settings
from app.models.team import Team
from app.models.subscription import  SubscriptionStatus, SubscriptionTier
from app.services.billing_service import BillingService
from app.middleware.auth_middleware import get_current_user
from app.models.user import User

router = APIRouter(prefix="/billing", tags=["billing"])

stripe.api_key = settings.stripe_secret_key


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        team_id = session["metadata"]["team_id"]
        tier = session["metadata"]["tier"]
        subscription_id = session["subscription"]
        
        # update team subscription
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if team:
            team.stripe_subscription_id = subscription_id
            team.subscription_tier = tier
            team.subscription_status = SubscriptionStatus.ACTIVE.value
            await db.commit()
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        result = await db.execute(
            select(Team).where(Team.stripe_subscription_id == subscription["id"])
        )
        team = result.scalar_one_or_none()
        if team:
            team.subscription_tier = SubscriptionTier.FREE.value
            team.subscription_status = SubscriptionStatus.CANCELLED.value
            team.stripe_subscription_id = None
            await db.commit()
    
    elif event["type"] == "invoice.payment_failed":
        subscription = event["data"]["object"]
        result = await db.execute(
            select(Team).where(Team.stripe_customer_id == subscription["customer"])
        )
        team = result.scalar_one_or_none()
        if team:
            team.subscription_status = SubscriptionStatus.PAST_DUE.value
            await db.commit()
    
    return {"status": "ok"}


@router.post("/checkout/{tier}")
async def create_checkout(
    tier: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    service = BillingService(db)
    url = await service.create_checkout_session(current_user.id, tier)
    return {"checkout_url": url}


@router.get("/status")
async def subscription_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    service = BillingService(db)
    return await service.get_subscription_status(current_user.id)


@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    service = BillingService(db)
    return await service.cancel_subscription(current_user.id)
