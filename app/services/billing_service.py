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
    def _amount(tier: str) -> int:
        amounts = {"plus": 3_000_000, "pro": 6_000_000}  # PKR paisas
        if tier not in amounts:
            raise HTTPException(status_code=400, detail="Invalid tier")
        return amounts[tier]

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
        amount = self._amount(tier)
        if not settings.safepay_public_key:
            raise HTTPException(status_code=503, detail="Safepay public key is not configured")
        reference = f"salesync_{team.id.hex}_{uuid4().hex}"
        payment_response = await self._request("POST", "/order/payments/v3/", json={
            "merchant_api_key": settings.safepay_public_key,
            "intent": "CYBERSOURCE",
            "mode": "payment",
            "entry_mode": "raw",
            "currency": "PKR",
            "amount": amount,
            "metadata": {"order_id": reference, "team_id": str(team.id), "tier": tier},
            "include_fees": False,
        })
        tracker = payment_response.json().get("data", {}).get("tracker", {}).get("token")
        if not isinstance(tracker, str) or not tracker.startswith("track_"):
            raise HTTPException(status_code=502, detail="Safepay returned an invalid payment tracker")

        # Persist the tracker before redirecting so the webhook can be correlated.
        now = datetime.now(timezone.utc)
        self.db.add(Subscription(
            team_id=team.id,
            stripe_subscription_id=tracker,
            stripe_price_id=f"manual-{tier}",
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
            "environment": settings.safepay_env,
            "tracker": tracker,
            "tbt": auth_token,
            "source": "hosted",
            "redirect_url": f"{frontend}/success",
            "cancel_url": f"{frontend}/billing/cancel",
        })
        return f"{settings.safepay_checkout_host.rstrip('/')}/embedded/?{params}"

    async def cancel_subscription(self, team_id: UUID):
        await self._get_team(team_id)
        raise HTTPException(status_code=400, detail="This plan does not auto-renew and does not need cancellation")

    async def get_subscription_status(self, team_id: UUID):
        team = await self._get_team(team_id)
        snapshot = await plan_snapshot(self.db, team_id)
        latest_sub = await self.db.scalar(
            select(Subscription).where(Subscription.team_id == team.id).order_by(Subscription.created_at.desc())
        )
        if latest_sub and latest_sub.status == SubscriptionStatus.ACTIVE.value and snapshot["tier"] != "free":
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
            "status": (
                "expired"
                if normalize_tier(team.subscription_tier) != "free" and snapshot["tier"] == "free"
                else getattr(team, "subscription_status", SubscriptionStatus.ACTIVE.value)
            ),
            "ends_at": getattr(team, "subscription_ends_at", None),
            "cancel_at_period_end": False,
            "limits": snapshot["limits"],
            "usage": snapshot["usage"],
        }
