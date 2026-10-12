from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.services.hunter_service import HunterService, hunter_error


@pytest.mark.parametrize("code,expected", [(401, 401), (403, 403), (429, 429), (500, 502)])
def test_hunter_errors_are_actionable(code, expected):
    response = httpx.Response(code, request=httpx.Request("GET", "https://api.hunter.io/v2/discover"))
    with pytest.raises(HTTPException) as error:
        hunter_error(response)
    assert error.value.status_code == expected


@pytest.mark.asyncio
async def test_discover_only_returns_valid_domains_without_spending_credits():
    db = SimpleNamespace()
    service = HunterService(db)
    service._key = AsyncMock(return_value=(SimpleNamespace(used_this_month=0), "secret"))
    response = httpx.Response(200, json={"data": [
        {"domain": "example.com", "organization": "Example", "emails_count": {"total": 3}},
        {"domain": "invalid domain", "organization": "Bad"},
    ]}, request=httpx.Request("POST", "https://api.hunter.io/v2/discover"))
    client = AsyncMock()
    client.post.return_value = response
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.hunter_service.httpx.AsyncClient", return_value=context):
        result = await service.discover(uuid4(), "software companies")
    assert result == [{"domain": "example.com", "name": "Example", "email_count": 3}]
    assert client.post.call_args.kwargs["headers"] == {"X-API-KEY": "secret"}


@pytest.mark.asyncio
async def test_reveal_rejects_more_than_three_domains_before_external_call():
    service = HunterService(SimpleNamespace())
    service._key = AsyncMock(return_value=(SimpleNamespace(used_this_month=0, monthly_limit=50), "secret"))
    with pytest.raises(HTTPException) as error:
        await service.reveal(uuid4(), ["one.com", "two.com", "three.com", "four.com"])
    assert error.value.status_code == 400
