from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models.lead import Lead
from app.routers import billing as billing_router
from tests.teams.test_team_api import create_team


@pytest.mark.asyncio
async def test_core_04_production_unexpected_exception_is_generic_and_redacted(
    monkeypatch,
):
    secret_marker = "postgresql://private_user:private_password@db.internal/prod"
    monkeypatch.setattr(settings, "app_env", "production")
    malformed_event = {
        "id": f"evt_{uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {"object": {"subscription": secret_marker, "metadata": {}}},
    }
    monkeypatch.setattr(
        billing_router.stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: malformed_event,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/billing/webhook",
            content=b"synthetic-provider-payload",
            headers={
                "stripe-signature": "synthetic-signature",
                "authorization": "Bearer secret-token-marker",
            },
        )

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "message": "Internal server error",
        "data": None,
        "error": "Internal server error",
    }
    serialized = response.text.lower()
    for forbidden in (
        "traceback",
        "private_user",
        "private_password",
        "db.internal",
        "postgresql://",
        "secret-token-marker",
        "keyerror",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_core_05_cors_origin_and_preflight_policy(client):
    allowed_origin = "http://127.0.0.1:5173"
    unknown_origin = "https://attacker.example.invalid"

    allowed = await client.get("/health", headers={"Origin": allowed_origin})
    unknown = await client.get("/health", headers={"Origin": unknown_origin})
    null_origin = await client.get("/health", headers={"Origin": "null"})
    preflight = await client.options(
        "/leads/",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-team-id",
        },
    )
    denied_preflight = await client.options(
        "/leads/",
        headers={
            "Origin": unknown_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-team-id",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == allowed_origin
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in unknown.headers
    assert "access-control-allow-origin" not in null_origin.headers
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == allowed_origin
    assert "POST" in preflight.headers["access-control-allow-methods"]
    allowed_headers = preflight.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "content-type", "x-team-id"):
        assert header in allowed_headers
    assert denied_preflight.status_code == 400
    assert "access-control-allow-origin" not in denied_preflight.headers


@pytest.mark.asyncio
async def test_core_06_sql_json_and_html_payloads_remain_inert_data(
    client, api_user
):
    user = await api_user("core-06")
    sql_payload = "'; DROP TABLE leads; --"
    html_payload = "<img src=x onerror=alert('xss')>"
    json_payload = '{"$ne":null,"__proto__":{"polluted":true}}'
    team_name = f"{sql_payload} {html_payload}"
    team = await create_team(client, user, team_name)
    headers = {**user["headers"], "X-Team-Id": team["id"]}

    created = await client.post(
        "/leads/",
        json={
            "name": sql_payload,
            "company": html_payload,
            "title": json_payload,
            "email": f"core06-{uuid4().hex}@example.com",
            "source": f"{sql_payload}{json_payload}",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    lead = created.json()["data"]
    assert lead["name"] == sql_payload
    async with SessionLocal() as db:
        stored = (
            await db.execute(select(Lead).where(Lead.id == lead["id"]))
        ).scalar_one()
        assert stored.company_name == html_payload
        assert stored.job_title == json_payload
        assert stored.source == f"{sql_payload}{json_payload}"

    patched = await client.patch(
        f"/leads/{lead['id']}",
        json={"name": html_payload, "company": sql_payload, "title": json_payload},
        headers=headers,
    )
    filtered = await client.get(
        "/leads/",
        params={"status": f"New{sql_payload}{html_payload}{json_payload}"},
        headers=headers,
    )
    fetched_team = await client.get(f"/teams/{team['id']}", headers=headers)
    health = await client.get("/health")

    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["name"] == html_payload
    async with SessionLocal() as db:
        stored = (
            await db.execute(select(Lead).where(Lead.id == lead["id"]))
        ).scalar_one()
        assert stored.company_name == sql_payload
        assert stored.job_title == json_payload
    assert filtered.status_code in {200, 400, 422}
    assert fetched_team.status_code == health.status_code == 200
    assert fetched_team.json()["data"]["name"] == team_name
    listed = await client.get("/leads/", headers=headers)
    assert listed.status_code == 200
    assert lead["id"] in {item["id"] for item in listed.json()["data"]}
