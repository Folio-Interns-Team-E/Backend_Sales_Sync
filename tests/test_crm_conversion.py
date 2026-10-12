from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.crm_conversion_service import _business_domain, convert_lead


def test_consumer_email_is_not_used_as_company_domain():
    assert _business_domain("person@gmail.com") is None
    assert _business_domain("person@example.com") == "example.com"


@pytest.mark.asyncio
async def test_conversion_is_idempotent_for_already_linked_lead():
    team_id, user_id, lead_id, contact_id = (uuid4() for _ in range(4))
    lead = SimpleNamespace(id=lead_id, team_id=team_id, status="Converted", crm_contact_id=contact_id)
    contact = SimpleNamespace(id=contact_id, team_id=team_id, account_id=None)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: lead)),
        scalar=AsyncMock(return_value=contact),
        commit=AsyncMock(),
    )

    result = await convert_lead(db, team_id, user_id, lead_id)

    assert result == {"contact_id": contact_id, "account_id": None, "already_converted": True}
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_conversion_does_not_use_another_workspaces_lead():
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))

    with pytest.raises(HTTPException) as error:
        await convert_lead(db, uuid4(), uuid4(), uuid4())

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_conversion_requires_qualified_prospect():
    lead = SimpleNamespace(status="New", crm_contact_id=None)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: lead)))

    with pytest.raises(HTTPException) as error:
        await convert_lead(db, uuid4(), uuid4(), uuid4())

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_conversion_creates_linked_account_and_contact_once():
    team_id, user_id, lead_id = uuid4(), uuid4(), uuid4()
    lead = SimpleNamespace(id=lead_id, team_id=team_id, status="Qualified", crm_contact_id=None,
                           email="Sally@acme.example", company_name="Acme", name="Sally Smith", job_title="CEO")
    async def execute(*_args, **_kwargs):
        return SimpleNamespace(scalar_one_or_none=lambda: lead)
    def add(row):
        row.id = uuid4()
    db = SimpleNamespace(execute=execute, scalar=AsyncMock(side_effect=[None, None, None]),
                         add=MagicMock(side_effect=add), flush=AsyncMock(), commit=AsyncMock())

    result = await convert_lead(db, team_id, user_id, lead_id)

    assert result["already_converted"] is False
    assert result["contact_id"] == lead.crm_contact_id
    assert lead.status == "Converted"
    assert db.add.call_count == 2
    assert db.add.call_args_list[0].args[0].domain == "acme.example"
    assert db.add.call_args_list[1].args[0].email == "sally@acme.example"
    db.commit.assert_awaited_once()
