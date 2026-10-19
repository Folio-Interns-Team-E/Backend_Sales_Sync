from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.team import Team
from app.services.plan_service import normalize_tier, plan_snapshot


def _frontend_base() -> str:
    raw = settings.frontend_origins[0] if settings.frontend_origins else "http://localhost:5173"
    return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_team(self, team_id: UUID) -> Team:
        team = await self.db.scalar(select(Team).where(Team.id == team_id))
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        return team

    @staticmethod
    def _plan_id(tier: str) -> str:
        plans = {"plus": settings.safepay_plus_plan_id, "pro": settings.safepay_pro_plan_id}
        if tier not in plans:
            raise HTTPException(status_code=400, detail="Invalid tier")
        if not plans[tier]:
            raise HTTPException(status_code=503, detail=f"{tier.title()} checkout is not configured")
        return plans[tier]

    @staticmethod
    async def _request(method: str, path: str, **kwargs) -> httpx.Response:
        if not settings.safepay_secret_key:
            raise HTTPException(status_code=503, detail="Safepay is not configured")
        headers = dict(kwargs.pop("headers", {}))
        headers["X-SFPY-MERCHANT-SECRET"] = settings.safepay_secret_key
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(
                    method,
                    f"{settings.safepay_host.rstrip('/')}{path}",
                    headers=headers,
                    **kwargs,
                )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Safepay request failed") from exc

    async def create_checkout_session(self, team_id: UUID, tier: str) -> str:
        team = await self._get_team(team_id)
        tier = normalize_tier(tier)
        plan_id = self._plan_id(tier)
        if team.subscription_tier == tier and team.subscription_status == SubscriptionStatus.ACTIVE.value:
            raise HTTPException(status_code=409, detail=f"Workspace is already on the {tier.title()} plan")

        # Safepay returns this reference in subscription webhooks. Persist it before
        # redirecting so a fast webhook can always be correlated to the workspace.
        reference = f"salesync_{team.id.hex}_{uuid4().hex}"
        now = datetime.now(timezone.utc)
        self.db.add(Subscription(
            team_id=team.id,
            stripe_subscription_id=reference,
            stripe_price_id=plan_id,
            tier=tier,
            status="pending",
            current_period_start=now,
            current_period_end=now,
        ))
        await self.db.commit()

        token_response = await self._request("POST", "/client/passport/v1/token", json={})
        auth_token = token_response.json().get("data")
        if not isinstance(auth_token, str) or not auth_token:
            raise HTTPException(status_code=502, detail="Safepay returned an invalid authorization token")

        frontend = _frontend_base().rstrip("/")
        params = urlencode({
            "plan_id": plan_id,
            "auth_token": auth_token,
            "env": settings.safepay_env,
            "reference": reference,
            "redirect_url": f"{frontend}/success",
            "cancel_url": f"{frontend}/billing/cancel",
        })
        return f"{settings.safepay_checkout_host.rstrip('/')}/checkout/subscribe?{params}"

    async def cancel_subscription(self, team_id: UUID):
        team = await self._get_team(team_id)
        active_sub = await self.db.scalar(
            select(Subscription)
            .where(
                Subscription.team_id == team.id,
                Subscription.status.in_([SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIALING.value]),
            )
            .order_by(Subscription.created_at.desc())
        )
        subscription_id = active_sub.stripe_subscription_id if active_sub else team.stripe_subscription_id
        if not subscription_id or not subscription_id.startswith("sub_"):
            raise HTTPException(status_code=400, detail="No active Safepay subscription found")
        await self._request("POST", f"/client/subscriptions/v1/{subscription_id}/cancel", json={})
        if active_sub:
            active_sub.cancel_at_period_end = True
        await self.db.commit()
        return {"message": "Subscription cancellation requested"}

    async def get_subscription_status(self, team_id: UUID):
        team = await self._get_team(team_id)
        snapshot = await plan_snapshot(self.db, team_id)
        latest_sub = await self.db.scalar(
            select(Subscription).where(Subscription.team_id == team.id).order_by(Subscription.created_at.desc())
        )
        if latest_sub and latest_sub.status != "pending":
            return {
                "tier": normalize_tier(latest_sub.tier),
                "status": latest_sub.status,
                "ends_at": latest_sub.current_period_end,
                "cancel_at_period_end": latest_sub.cancel_at_period_end,
                "limits": snapshot["limits"],
                "usage": snapshot["usage"],
            }
        return {
            "tier": snapshot["tier"],
            "status": getattr(team, "subscription_status", SubscriptionStatus.ACTIVE.value),
            "ends_at": getattr(team, "subscription_ends_at", None),
            "cancel_at_period_end": False,
            "limits": snapshot["limits"],
            "usage": snapshot["usage"],
        }
