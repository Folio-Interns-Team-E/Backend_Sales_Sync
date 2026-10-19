import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_team_context, require_role
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.models.team import Team
from app.models.team_member import MemberRole
from app.services.billing_service import BillingService
from app.services.plan_service import normalize_tier

router = APIRouter(prefix="/billing", tags=["billing"])


def _validate_checkout_team(metadata_team_id: object, team_ctx: TeamContext) -> UUID:
    """Compatibility guard for provider callbacks carrying a workspace identifier."""
    try:
        checkout_team_id = UUID(str(metadata_team_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid team_id in checkout metadata") from exc
    if checkout_team_id != team_ctx.team_id:
        raise HTTPException(status_code=403, detail="Checkout does not belong to the active team")
    return checkout_team_id


def _timestamp(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, dict):
        value = value.get("seconds")
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return fallback or datetime.now(timezone.utc)


def _valid_signature(raw_body: bytes, payload: dict, received: str | None) -> bool:
    if not settings.safepay_webhook_secret or not received:
        return False
    current = hmac.new(settings.safepay_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    legacy_body = json.dumps(payload.get("data", {}), separators=(",", ":")).encode()
    legacy = hmac.new(settings.safepay_webhook_secret.encode(), legacy_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(current, received) or hmac.compare_digest(legacy, received)


def _tier_for_plan(plan_id: str | None) -> str | None:
    mapping = {
        settings.safepay_plus_plan_id: SubscriptionTier.PLUS.value,
        settings.safepay_pro_plan_id: SubscriptionTier.PRO.value,
    }
    return mapping.get(plan_id) if plan_id else None


async def _find_subscription(db: AsyncSession, data: dict) -> Subscription | None:
    reference = data.get("reference")
    subscription_id = data.get("subscription_id") or data.get("sub_id") or data.get("id")
    identifiers = [value for value in (reference, subscription_id) if value]
    if not identifiers:
        return None
    return await db.scalar(
        select(Subscription)
        .where(Subscription.stripe_subscription_id.in_(identifiers))
        .order_by(Subscription.created_at.desc())
    )


@router.post("/webhook")
async def safepay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    try:
        event = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not _valid_signature(raw_body, event, request.headers.get("x-sfpy-signature")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event_type = str(event.get("type", ""))
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if not event_type.startswith("subscription."):
        return {"status": "ignored"}
    subscription = await _find_subscription(db, data)
    if not subscription:
        return {"status": "ignored"}

    subscription_id = data.get("subscription_id") or data.get("sub_id") or data.get("id")
    plan_id = data.get("plan_id")
    tier = _tier_for_plan(plan_id) or normalize_tier(subscription.tier)
    now = datetime.now(timezone.utc)
    period_start = _timestamp(data.get("current_period_start_date"), subscription.current_period_start)
    period_end = _timestamp(data.get("current_period_end_date"), subscription.current_period_end)
    team = await db.scalar(select(Team).where(Team.id == subscription.team_id))
    if not team:
        return {"status": "ignored"}

    if subscription_id:
        subscription.stripe_subscription_id = str(subscription_id)
        team.stripe_subscription_id = str(subscription_id)
    if plan_id:
        subscription.stripe_price_id = str(plan_id)
    subscription.tier = tier
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end

    if event_type == "subscription.created":
        subscription.status = "pending"
    elif event_type == "subscription.payment.succeeded":
        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.cancel_at_period_end = False
        team.subscription_tier = tier
        team.subscription_status = SubscriptionStatus.ACTIVE.value
        team.subscription_ends_at = period_end
    elif event_type == "subscription.payment.failed":
        subscription.status = SubscriptionStatus.PAST_DUE.value
        team.subscription_status = SubscriptionStatus.PAST_DUE.value
    elif event_type in {"subscription.cancelled", "subscription.canceled", "subscription.ended"}:
        subscription.status = SubscriptionStatus.CANCELED.value
        subscription.canceled_at = _timestamp(data.get("canceled_at"), now)
        subscription.ended_at = now
        team.subscription_tier = SubscriptionTier.FREE.value
        team.subscription_status = SubscriptionStatus.CANCELED.value
        team.subscription_ends_at = now
        team.stripe_subscription_id = None
    else:
        return {"status": "ignored"}

    await db.commit()
    return {"status": "ok"}


@router.post("/checkout/{tier}")
async def create_checkout(tier: str, team_ctx: TeamContext = Depends(require_role(MemberRole.admin)), db: AsyncSession = Depends(get_db)):
    return {"checkout_url": await BillingService(db).create_checkout_session(team_ctx.team_id, tier)}


@router.get("/status")
async def subscription_status(team_ctx: TeamContext = Depends(get_team_context), db: AsyncSession = Depends(get_db)):
    return await BillingService(db).get_subscription_status(team_ctx.team_id)


@router.post("/cancel")
async def cancel_subscription(team_ctx: TeamContext = Depends(require_role(MemberRole.admin)), db: AsyncSession = Depends(get_db)):
    return await BillingService(db).cancel_subscription(team_ctx.team_id)
