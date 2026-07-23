from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timezone
import stripe

from app.database import get_db
from app.config import settings
from app.models.team import Team
from app.models.subscription import Subscription, Invoice, SubscriptionStatus, SubscriptionTier
from app.services.billing_service import BillingService
from app.middleware.auth_middleware import get_team_context, TeamContext

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
        stripe_subscription_id = session["subscription"]
        
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if not team:
            return {"status": "ok"}

        team.stripe_subscription_id = stripe_subscription_id
        team.subscription_tier = tier
        team.subscription_status = SubscriptionStatus.ACTIVE.value

        sub_result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
        )
        existing_sub = sub_result.scalar_one_or_none()

        stripe_sub = await stripe.Subscription.retrieve_async(stripe_subscription_id)
        period_end = datetime.fromtimestamp(stripe_sub["current_period_end"], tz=timezone.utc)

        if existing_sub:
            existing_sub.tier = tier
            existing_sub.status = SubscriptionStatus.ACTIVE.value
            existing_sub.current_period_end = period_end
            existing_sub.cancel_at_period_end = False
        else:
            new_sub = Subscription(
                team_id=team_id,
                stripe_subscription_id=stripe_subscription_id,
                stripe_price_id=stripe_sub["items"]["data"][0]["price"]["id"],
                tier=tier,
                status=SubscriptionStatus.ACTIVE.value,
                current_period_start=datetime.fromtimestamp(stripe_sub["current_period_start"], tz=timezone.utc),
                current_period_end=period_end,
            )
            db.add(new_sub)

        team.subscription_ends_at = period_end
        await db.commit()
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        result = await db.execute(
            select(Team).where(Team.stripe_subscription_id == subscription["id"])
        )
        team = result.scalar_one_or_none()
        if team:
            team.subscription_tier = SubscriptionTier.FREE.value
            team.subscription_status = SubscriptionStatus.CANCELED.value
            team.stripe_subscription_id = None

        sub_result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription["id"])
        )
        sub = sub_result.scalar_one_or_none()
        if sub:
            sub.status = SubscriptionStatus.CANCELED.value
            ended_at = subscription["ended_at"]
            if ended_at:
                sub.ended_at = datetime.fromtimestamp(ended_at, tz=timezone.utc)

        await db.commit()
    
    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        result = await db.execute(
            select(Team).where(Team.stripe_customer_id == invoice["customer"])
        )
        team = result.scalar_one_or_none()
        if team:
            team.subscription_status = SubscriptionStatus.PAST_DUE.value

            sub_result = await db.execute(
                select(Subscription)
                .where(Subscription.team_id == team.id)
                .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
                .order_by(Subscription.created_at.desc())
            )
            sub = sub_result.scalar_one_or_none()
            if sub:
                sub.status = SubscriptionStatus.PAST_DUE.value

        await db.commit()
    
    return {"status": "ok"}


class CheckoutCompleteRequest(BaseModel):
    session_id: str


def to_clean_dict(obj):
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, dict):
        return obj
    return dict(obj)


@router.post("/checkout/complete")
async def checkout_complete(
    body: CheckoutCompleteRequest,
    team_ctx: TeamContext = Depends(get_team_context),
    db: AsyncSession = Depends(get_db),
):
    # 1. Retrieve and normalize Session
    try:
        session_obj = await stripe.checkout.Session.retrieve_async(body.session_id)
        # to_dict() works reliably on all modern Stripe SDK objects
        session = to_clean_dict(session_obj)
    except stripe.error.InvalidRequestError:
        raise HTTPException(status_code=400, detail="Invalid Stripe session")

    if session.get("payment_status") != "paid":
        raise HTTPException(status_code=400, detail="Payment not completed")

    # 2. Extract Metadata cleanly
    metadata = session.get("metadata") or {}
    team_id = metadata.get("team_id")
    tier = metadata.get("tier")
    
    if not team_id:
        raise HTTPException(status_code=400, detail="Missing team_id in session metadata")
    if not tier:
        raise HTTPException(status_code=400, detail="Missing tier in session metadata")

    stripe_subscription_id = session.get("subscription")
    if not stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No subscription in session")

    # 3. Database lookup
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    team.stripe_subscription_id = stripe_subscription_id
    team.subscription_tier = tier
    team.subscription_status = SubscriptionStatus.ACTIVE.value

    # 4. Retrieve and normalize Subscription
    sub_obj = await stripe.Subscription.retrieve_async(stripe_subscription_id)
    stripe_sub = to_clean_dict(sub_obj)

    # Extract price_id safely
    items_data = stripe_sub.get("items", {}).get("data", [])
    first_item = to_clean_dict(items_data[0]) if items_data else {}
    
    price_id = None
    if first_item and "price" in first_item:
        price_obj = to_clean_dict(first_item["price"])
        price_id = price_obj.get("id")

    # Safely retrieve period timestamps
    period_start_ts = stripe_sub.get("current_period_start")
    period_end_ts = stripe_sub.get("current_period_end")

    if not period_start_ts and first_item:
        period_start_ts = first_item.get("current_period_start")
        period_end_ts = first_item.get("current_period_end")

    now = datetime.now(timezone.utc)
    period_start = datetime.fromtimestamp(period_start_ts, tz=timezone.utc) if period_start_ts else now
    period_end = datetime.fromtimestamp(period_end_ts, tz=timezone.utc) if period_end_ts else now
    
    team.subscription_ends_at = period_end

    # 5. Upsert Subscription DB Model
    sub_result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
    )
    existing_sub = sub_result.scalar_one_or_none()

    if existing_sub:
        existing_sub.tier = tier
        existing_sub.status = SubscriptionStatus.ACTIVE.value
        existing_sub.stripe_price_id = price_id
        existing_sub.current_period_start = period_start
        existing_sub.current_period_end = period_end
        existing_sub.cancel_at_period_end = False
    else:
        db.add(Subscription(
            team_id=team_id,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=price_id,
            tier=tier,
            status=SubscriptionStatus.ACTIVE.value,
            current_period_start=period_start,
            current_period_end=period_end,
        ))

    # 6. Retrieve and normalize Invoice (if present)
    invoice_id = session.get("invoice")
    if invoice_id:
        try:
            inv_obj = await stripe.Invoice.retrieve_async(invoice_id)
            stripe_invoice = to_clean_dict(inv_obj)
            inv_id = stripe_invoice.get("id")
            
            inv_result = await db.execute(
                select(Invoice).where(Invoice.stripe_invoice_id == inv_id)
            )
            if not inv_result.scalar_one_or_none():
                db.add(Invoice(
                    team_id=team_id,
                    stripe_invoice_id=inv_id,
                    stripe_payment_intent_id=stripe_invoice.get("payment_intent"),
                    amount_due=stripe_invoice.get("amount_due", 0),
                    amount_paid=stripe_invoice.get("amount_paid", 0),
                    currency=stripe_invoice.get("currency", "usd"),
                    status=stripe_invoice.get("status", "paid"),
                    hosted_invoice_url=stripe_invoice.get("hosted_invoice_url"),
                    invoice_pdf=stripe_invoice.get("invoice_pdf"),
                    created_at=datetime.fromtimestamp(stripe_invoice.get("created"), tz=timezone.utc) if stripe_invoice.get("created") else now,
                ))
        except Exception:
            pass

    await db.commit()

    service = BillingService(db)
    return await service.get_subscription_status(team_id)

@router.post("/checkout/{tier}")
async def create_checkout(
    tier: str,
    team_ctx: TeamContext = Depends(get_team_context),
    db: AsyncSession = Depends(get_db)
):
    service = BillingService(db)
    url = await service.create_checkout_session(team_ctx.team_id, tier)
    return {"checkout_url": url}


@router.get("/status")
async def subscription_status(
    team_ctx: TeamContext = Depends(get_team_context),
    db: AsyncSession = Depends(get_db)
):
    service = BillingService(db)
    return await service.get_subscription_status(team_ctx.team_id)


@router.post("/cancel")
async def cancel_subscription(
    team_ctx: TeamContext = Depends(get_team_context),
    db: AsyncSession = Depends(get_db)
):
    service = BillingService(db)
    return await service.cancel_subscription(team_ctx.team_id)
