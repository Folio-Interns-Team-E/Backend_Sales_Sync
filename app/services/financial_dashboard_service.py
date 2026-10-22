from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.opportunity import Opportunity, OpportunityStage
from app.models.team_member import MemberRole


def _money_map(values: dict[str, Decimal]) -> dict[str, str]:
    return {currency: str(amount.quantize(Decimal("0.01"))) for currency, amount in sorted(values.items())}


def aggregate_financial_dashboard(won, lost, previous_won=None) -> dict:
    previous_won = previous_won or []
    revenue = defaultdict(lambda: Decimal("0"))
    previous_revenue = defaultdict(lambda: Decimal("0"))
    monthly = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    owners = {}
    cycle_days = []

    for deal in previous_won:
        previous_revenue[deal.currency] += deal.amount

    for deal in won:
        revenue[deal.currency] += deal.amount
        closed_at = deal.closed_at or deal.updated_at
        month = closed_at.strftime("%Y-%m")
        monthly[month][deal.currency] += deal.amount
        owner_key = str(deal.owner_id) if deal.owner_id else "unassigned"
        owner = owners.setdefault(owner_key, {
            "owner_id": str(deal.owner_id) if deal.owner_id else None,
            "owner_name": deal.owner.full_name if getattr(deal, "owner", None) else "Unassigned",
            "won_deals": 0,
            "revenue": defaultdict(lambda: Decimal("0")),
        })
        owner["won_deals"] += 1
        owner["revenue"][deal.currency] += deal.amount
        if deal.created_at and closed_at:
            cycle_days.append(max(0, (closed_at - deal.created_at).days))

    total_closed = len(won) + len(lost)
    averages = {
        currency: str((amount / sum(1 for deal in won if deal.currency == currency)).quantize(Decimal("0.01")))
        for currency, amount in revenue.items()
    }
    growth = {}
    for currency in set(revenue) | set(previous_revenue):
        current = revenue[currency]
        previous = previous_revenue[currency]
        growth[currency] = None if previous == 0 else round(float((current - previous) / previous * 100), 1)

    return {
        "summary": {
            "won_deals": len(won),
            "lost_deals": len(lost),
            "win_rate": round((len(won) / total_closed * 100) if total_closed else 0, 1),
            "average_sales_cycle_days": round(sum(cycle_days) / len(cycle_days), 1) if cycle_days else 0,
            "revenue": _money_map(revenue),
            "average_deal_size": averages,
            "revenue_growth": growth,
        },
        "monthly_revenue": [
            {"month": month, "revenue": _money_map(values)}
            for month, values in sorted(monthly.items())
        ],
        "owner_performance": sorted([
            {**owner, "revenue": _money_map(owner["revenue"])} for owner in owners.values()
        ], key=lambda item: item["won_deals"], reverse=True),
        "won_deals": [
            {
                "id": str(deal.id),
                "name": deal.name,
                "company_name": deal.company_name,
                "owner_name": deal.owner.full_name if getattr(deal, "owner", None) else "Unassigned",
                "amount": str(deal.amount),
                "currency": deal.currency,
                "closed_at": (deal.closed_at or deal.updated_at).isoformat(),
                "sales_cycle_days": max(0, ((deal.closed_at or deal.updated_at) - deal.created_at).days),
            }
            for deal in won
        ],
    }


class FinancialDashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _visible(query, user_id: UUID, role: MemberRole):
        if role == MemberRole.rep:
            return query.where(or_(Opportunity.owner_id == user_id, Opportunity.owner_id.is_(None)))
        return query

    async def dashboard(
        self,
        team_id: UUID,
        user_id: UUID,
        role: MemberRole,
        from_date: date | None,
        to_date: date | None,
    ) -> dict:
        start = datetime.combine(from_date, time.min, timezone.utc) if from_date else None
        end = datetime.combine(to_date + timedelta(days=1), time.min, timezone.utc) if to_date else None

        base = select(Opportunity).where(
            Opportunity.team_id == team_id,
            Opportunity.stage.in_([OpportunityStage.CLOSED_WON.value, OpportunityStage.CLOSED_LOST.value]),
        ).options(selectinload(Opportunity.owner))
        if start:
            base = base.where(Opportunity.closed_at >= start)
        if end:
            base = base.where(Opportunity.closed_at < end)
        records = list((await self.db.execute(
            self._visible(base.order_by(Opportunity.closed_at.desc()), user_id, role)
        )).scalars().all())

        previous_won = []
        if start and end:
            period = end - start
            previous = select(Opportunity).where(
                Opportunity.team_id == team_id,
                Opportunity.stage == OpportunityStage.CLOSED_WON.value,
                Opportunity.closed_at >= start - period,
                Opportunity.closed_at < start,
            ).options(selectinload(Opportunity.owner))
            previous_won = list((await self.db.execute(
                self._visible(previous, user_id, role)
            )).scalars().all())

        won = [record for record in records if record.stage == OpportunityStage.CLOSED_WON.value]
        lost = [record for record in records if record.stage == OpportunityStage.CLOSED_LOST.value]
        result = aggregate_financial_dashboard(won, lost, previous_won)
        result["period"] = {
            "from": from_date.isoformat() if from_date else None,
            "to": to_date.isoformat() if to_date else None,
        }
        return result
