"""Subscription entitlements and usage enforcement.

All product limits live here so API routes and billing responses cannot drift from
the public pricing page. Limits are workspace-wide.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from app.models.email import Email, EmailStatus
from app.models.lead import Lead
from app.models.proposal import Proposal
from app.models.sequence import Sequence, SequenceDelivery
from app.models.team import Team
from app.models.team_member import TeamMember


@dataclass(frozen=True)
class PlanLimits:
    members: int
    leads: int
    ai_actions_monthly: int
    emails_monthly: int
    active_sequences: int
    proposals_monthly: int


PLAN_LIMITS = {
    "free": PlanLimits(1, 100, 25, 50, 1, 3),
    "plus": PlanLimits(5, 5_000, 1_000, 2_000, 20, 100),
    "pro": PlanLimits(15, 25_000, 5_000, 10_000, 100, 500),
}

# Existing subscriptions keep their equivalent access after the tier rename.
TIER_ALIASES = {"growth": "plus", "enterprise": "pro"}


def normalize_tier(tier: str | None) -> str:
    value = (tier or "free").lower()
    return TIER_ALIASES.get(value, value) if value in PLAN_LIMITS or value in TIER_ALIASES else "free"


def month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


async def get_team_tier(db: AsyncSession, team_id: UUID) -> str:
    team = await db.scalar(select(Team).where(Team.id == team_id))
    if not team:
        return "free"
    tier = normalize_tier(team.subscription_tier)
    if tier != "free" and team.subscription_ends_at and team.subscription_ends_at <= datetime.now(timezone.utc):
        return "free"
    return tier


async def get_usage(db: AsyncSession, team_id: UUID) -> dict[str, int]:
    start = month_start()
    members = await db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team_id))
    leads = await db.scalar(select(func.count()).select_from(Lead).where(Lead.team_id == team_id))
    ai_actions = await db.scalar(
        select(func.count()).select_from(ChatMessage).where(
            ChatMessage.team_id == team_id,
            ChatMessage.sent_by == "user",
            ChatMessage.created_at >= start,
        )
    )
    direct_emails = await db.scalar(
        select(func.count()).select_from(Email).join(Lead, Lead.id == Email.lead_id).where(
            Lead.team_id == team_id,
            Email.status == EmailStatus.SENT,
            Email.sent_at >= start,
        )
    )
    sequence_emails = await db.scalar(
        select(func.count()).select_from(SequenceDelivery).join(
            Sequence, Sequence.id == SequenceDelivery.sequence_id
        ).where(
            Sequence.team_id == team_id,
            SequenceDelivery.status == "Sent",
            SequenceDelivery.sent_at >= start,
        )
    )
    active_sequences = await db.scalar(
        select(func.count()).select_from(Sequence).where(
            Sequence.team_id == team_id,
            Sequence.status == "Active",
        )
    )
    proposals = await db.scalar(
        select(func.count()).select_from(Proposal).where(
            Proposal.team_id == team_id,
            Proposal.created_at >= start,
        )
    )
    return {
        "members": members or 0,
        "leads": leads or 0,
        "ai_actions_monthly": ai_actions or 0,
        "emails_monthly": (direct_emails or 0) + (sequence_emails or 0),
        "active_sequences": active_sequences or 0,
        "proposals_monthly": proposals or 0,
    }


async def plan_snapshot(db: AsyncSession, team_id: UUID) -> dict:
    tier = await get_team_tier(db, team_id)
    return {"tier": tier, "limits": asdict(PLAN_LIMITS[tier]), "usage": await get_usage(db, team_id)}


async def enforce_limit(db: AsyncSession, team_id: UUID, metric: str, increment: int = 1) -> None:
    snapshot = await plan_snapshot(db, team_id)
    limit = snapshot["limits"][metric]
    used = snapshot["usage"][metric]
    if used + increment > limit:
        label = metric.replace("_monthly", " per month").replace("_", " ")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Your {snapshot['tier'].title()} plan allows {limit:,} {label}. Upgrade your plan to continue.",
        )
