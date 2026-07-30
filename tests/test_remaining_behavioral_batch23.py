from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app import main as main_module
from app.routers import billing as billing_router
from tests.test_teams import create_team


ENVELOPE_KEYS = {"success", "message", "data", "error"}


def _assert_envelope(body: dict, *, success: bool):
    assert set(body) == ENVELOPE_KEYS
    assert body["success"] is success
    assert isinstance(body["message"], str) and body["message"]
    if success:
        assert body["error"] is None
    else:
        assert body["data"] is None
        assert body["error"] not in (None, "")


@pytest.mark.asyncio
async def test_core_01_health_reports_database_unavailability_without_secrets(
    client, monkeypatch
):
    healthy = await client.get("/health")
    _assert_envelope(healthy.json(), success=True)
    assert healthy.status_code == 200
    assert healthy.json()["data"]["status"] == "ok"

    class BrokenEngine:
        def connect(self):
            raise RuntimeError(
                "database unavailable at postgresql://user:password@private-host/db"
            )

    monkeypatch.setattr(main_module, "engine", BrokenEngine())
    unavailable = await client.get("/health")

    assert unavailable.status_code == 503
    _assert_envelope(unavailable.json(), success=False)
    serialized = str(unavailable.json()).lower()
    assert "password" not in serialized
    assert "private-host" not in serialized
    assert "postgresql://" not in serialized


@pytest.mark.asyncio
async def test_core_02_representative_success_responses_share_api_envelope(
    client, api_user
):
    register_user = await api_user("core-02")
    team = await create_team(client, register_user, "CORE-02 Team")
    headers = {**register_user["headers"], "X-Team-Id": team["id"]}
    responses = [
        await client.get("/health"),
        await client.get("/teams/", headers=register_user["headers"]),
        await client.get("/onboarding/status", headers=headers),
        await client.get("/leads/", headers=headers),
        await client.get("/meetings/", headers=headers),
        await client.get("/proposals/", headers=headers),
        await client.get("/knowledge-base/", headers=headers),
        await client.get("/chat/", headers=headers),
        await client.get("/billing/status", headers=headers),
    ]

    assert all(response.status_code == 200 for response in responses)
    for response in responses:
        _assert_envelope(response.json(), success=True)


@pytest.mark.asyncio
async def test_core_03_error_statuses_use_one_frontend_readable_envelope(
    client, api_user, monkeypatch
):
    owner = await api_user("core-03-owner")
    outsider = await api_user("core-03-outsider")
    team = await create_team(client, owner, "CORE-03 Team")

    error_responses = {
        400: await client.get(
            "/billing/status",
            headers={**owner["headers"], "X-Team-Id": "not-a-uuid"},
        ),
        401: await client.get("/teams/"),
        403: await client.get(
            f"/teams/{team['id']}",
            headers={**outsider["headers"], "X-Team-Id": team["id"]},
        ),
        404: await client.get(
            f"/chat/{uuid4()}",
            headers={**owner["headers"], "X-Team-Id": team["id"]},
        ),
        422: await client.post("/teams/", json={}, headers=owner["headers"]),
    }

    malformed_event = {
        "id": f"evt_{uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {"object": {"subscription": f"sub_{uuid4().hex}", "metadata": {}}},
    }
    monkeypatch.setattr(
        billing_router.stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: malformed_event,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        error_responses[500] = await safe_client.post(
            "/billing/webhook",
            content=b"synthetic-event",
            headers={"stripe-signature": "verified-at-provider-boundary"},
        )

    for expected_status, response in error_responses.items():
        assert response.status_code == expected_status
        _assert_envelope(response.json(), success=False)
        assert "traceback" not in response.text.lower()
        assert "e2e-only-jwt-secret" not in response.text
