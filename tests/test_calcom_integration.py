from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.calcom_service import cal_headers, verify_calcom_credentials


def test_calcom_headers_never_put_secret_in_the_url():
    headers = cal_headers("cal_live_secret")
    assert headers["Authorization"] == "Bearer cal_live_secret"
    assert headers["cal-api-version"]


async def test_calcom_rejects_invalid_credentials_before_storage():
    client = AsyncMock()
    client.get.return_value = SimpleNamespace(status_code=401)
    with patch("app.services.calcom_service.httpx.AsyncClient") as client_factory:
        client_factory.return_value.__aenter__.return_value = client
        with pytest.raises(HTTPException) as error:
            await verify_calcom_credentials("invalid-key", "123")
    assert error.value.status_code == 422


async def test_calcom_accepts_verified_event_type():
    client = AsyncMock()
    client.get.return_value = SimpleNamespace(status_code=200)
    with patch("app.services.calcom_service.httpx.AsyncClient") as client_factory:
        client_factory.return_value.__aenter__.return_value = client
        await verify_calcom_credentials("cal_live_valid", "123")
    requested_url = client.get.await_args.args[0]
    assert requested_url.endswith("/event-types/123")
