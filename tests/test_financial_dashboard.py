from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.financial_dashboard_service import aggregate_financial_dashboard


def deal(amount, currency, closed_at, owner="Ayesha Khan"):
    return SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        owner=SimpleNamespace(full_name=owner),
        name="Implementation deal",
        company_name="Example Co",
        amount=Decimal(amount),
        currency=currency,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        closed_at=closed_at,
        updated_at=closed_at,
    )


def test_financial_dashboard_keeps_currencies_separate_and_calculates_metrics():
    won = [
        deal("100000", "PKR", datetime(2026, 2, 1, tzinfo=timezone.utc)),
        deal("50000", "PKR", datetime(2026, 2, 15, tzinfo=timezone.utc)),
        deal("1000", "USD", datetime(2026, 3, 1, tzinfo=timezone.utc)),
    ]
    lost = [SimpleNamespace()]
    previous = [deal("100000", "PKR", datetime(2026, 1, 1, tzinfo=timezone.utc))]

    result = aggregate_financial_dashboard(won, lost, previous)

    assert result["summary"]["revenue"] == {"PKR": "150000.00", "USD": "1000.00"}
    assert result["summary"]["average_deal_size"]["PKR"] == "75000.00"
    assert result["summary"]["win_rate"] == 75.0
    assert result["summary"]["revenue_growth"]["PKR"] == 50.0
    assert result["summary"]["revenue_growth"]["USD"] is None
    assert [row["month"] for row in result["monthly_revenue"]] == ["2026-02", "2026-03"]
    assert len(result["won_deals"]) == 3


def test_financial_dashboard_handles_empty_period():
    result = aggregate_financial_dashboard([], [])

    assert result["summary"]["won_deals"] == 0
    assert result["summary"]["win_rate"] == 0
    assert result["summary"]["revenue"] == {}
    assert result["monthly_revenue"] == []
