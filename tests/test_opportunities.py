from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.opportunity import OpportunityStage
from app.models.team_member import MemberRole
from app.schemas.opportunities import OpportunityCreate
from app.services.opportunities_service import OpportunityService


def test_opportunity_payload_normalizes_currency():
    payload = OpportunityCreate(name="Enterprise rollout", company_name="Acme", currency="pkr")
    assert payload.currency == "PKR"
    assert payload.stage == OpportunityStage.PROSPECTING


def test_opportunity_payload_rejects_invalid_probability():
    with pytest.raises(ValidationError):
        OpportunityCreate(name="Enterprise rollout", company_name="Acme", probability=101)


@pytest.mark.asyncio
async def test_rep_cannot_assign_deal_to_another_user():
    service = OpportunityService(SimpleNamespace())
    with pytest.raises(HTTPException) as exc:
        await service.create(
            uuid4(),
            uuid4(),
            MemberRole.rep,
            OpportunityCreate(name="Enterprise rollout", company_name="Acme", owner_id=uuid4()),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_summary_calculates_weighted_pipeline():
    service = OpportunityService(SimpleNamespace())
    service.list = lambda *_: None

    async def records(*_):
        return [
            SimpleNamespace(stage="Proposal", amount=Decimal("1000"), probability=60),
            SimpleNamespace(stage="Negotiation", amount=Decimal("500"), probability=80),
            SimpleNamespace(stage="Closed Won", amount=Decimal("250"), probability=100),
            SimpleNamespace(stage="Closed Lost", amount=Decimal("300"), probability=0),
        ]

    service.list = records
    summary = await service.summary(uuid4(), uuid4(), MemberRole.admin)
    assert summary.pipeline_value == Decimal("1500")
    assert summary.weighted_value == Decimal("1000")
    assert summary.won_value == Decimal("250")
