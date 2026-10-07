from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.lead_generation_service import LeadGenerationService


def result_one(value):
    return SimpleNamespace(scalar_one_or_none=lambda: value)


def result_many(values):
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))


async def test_apollo_generation_requires_configuration():
    service = LeadGenerationService(AsyncMock())
    criteria = {"titles": [], "seniorities": [], "locations": [], "keywords": ""}
    with patch("app.services.lead_generation_service.settings.apollo_api_key", ""):
        with pytest.raises(HTTPException) as error:
            await service._search_apollo(criteria, 10)
    assert error.value.status_code == 503


async def test_generation_deduplicates_existing_and_batch_results():
    team_id = uuid4()
    team = SimpleNamespace(id=team_id, icp="Sales leaders at B2B software companies")
    database = SimpleNamespace(
        execute=AsyncMock(side_effect=[result_one(team), result_many(["existing@example.com"])]),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    service = LeadGenerationService(database)
    prospects = [
        {"apollo_id": "1", "name": "Existing", "email": "existing@example.com", "title": "VP Sales", "company": "A", "country": None, "city": None, "linkedin_url": None, "raw": {}},
        {"apollo_id": "2", "name": "New Person", "email": "new@example.com", "title": "VP Sales", "company": "B", "country": "Pakistan", "city": None, "linkedin_url": None, "raw": {}},
        {"apollo_id": "3", "name": "Duplicate", "email": "new@example.com", "title": "Director", "company": "B", "country": None, "city": None, "linkedin_url": None, "raw": {}},
    ]
    with (
        patch("app.services.lead_generation_service.get_provider", new=AsyncMock(return_value=None)),
        patch("app.services.lead_generation_service.settings.apollo_api_key", "platform-key"),
        patch.object(service, "_criteria_from_icp", new=AsyncMock(return_value={})),
        patch.object(service, "_search_apollo", new=AsyncMock(return_value=[{"id": "1"}, {"id": "2"}, {"id": "3"}])),
        patch.object(service, "_enrich_person", new=AsyncMock(side_effect=prospects)),
        patch.object(service, "_score", new=AsyncMock(return_value={"2": {"score": 91, "reasoning": "Strong title and segment match."}})),
    ):
        leads, skipped = await service.generate(team_id, 10)

    assert len(leads) == 1
    assert skipped == 2
    assert leads[0].email == "new@example.com"
    assert leads[0].score == 91
    assert leads[0].source == "Apollo"
    database.commit.assert_awaited_once()


async def test_generation_requires_an_icp_before_spending_provider_credits():
    team_id = uuid4()
    database = SimpleNamespace(execute=AsyncMock(return_value=result_one(SimpleNamespace(id=team_id, icp=""))))
    service = LeadGenerationService(database)
    with patch.object(service, "_search_apollo", new_callable=AsyncMock) as search:
        with pytest.raises(HTTPException) as error:
            await service.generate(team_id)
    assert error.value.status_code == 400
    search.assert_not_awaited()
