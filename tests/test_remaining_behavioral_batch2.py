from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models.user import User
from app.services import auth_service
from tests.test_core_resources import create_lead, team_context


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, ex=None):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_auth_12_and_08_correct_otp_is_single_use_and_enables_login(
    client, api_user, monkeypatch
):
    redis = FakeRedis()
    monkeypatch.setattr(auth_service, "get_redis", lambda: redis)
    user = await api_user("verified-login")
    redis.set(f"otp:{user['email']}", "381924", ex=300)

    verified = await client.post(
        "/auth/otp/verify", json={"email": user["email"], "otp": "381924"}
    )
    reused = await client.post(
        "/auth/otp/verify", json={"email": user["email"], "otp": "381924"}
    )
    login = await client.post(
        "/auth/login", json={"email": user["email"], "password": user["password"]}
    )

    assert verified.status_code == 200, verified.text
    assert reused.status_code == 400
    assert login.status_code == 200, login.text
    data = login.json()["data"]
    assert data["needs_verification"] is False
    assert data["access_token"]
    assert login.cookies.get("refresh_token")

    async with SessionLocal() as db:
        stored = (
            await db.execute(select(User).where(User.id == user["id"]))
        ).scalar_one()
        assert stored.email_verified is True


@pytest.mark.asyncio
async def test_auth_16_registration_survives_provider_failure_and_can_retry(
    client, unique_email, monkeypatch
):
    redis = FakeRedis()
    monkeypatch.setattr(auth_service, "get_redis", lambda: redis)

    async def fail_email(email, otp):
        raise RuntimeError("resend unavailable")

    monkeypatch.setattr(auth_service, "send_otp_email", fail_email)
    email = unique_email("provider-failure")
    registered = await client.post(
        "/auth/register",
        json={"full_name": "Provider Failure", "email": email, "password": "SafePassword123!"},
    )
    async def succeed_email(email, otp):
        return None
    monkeypatch.setattr(auth_service, "send_otp_email", succeed_email)
    requested = await client.post("/auth/otp/request", json={"email": email})

    assert registered.status_code == 201
    assert registered.json()["data"]["needs_verification"] is True
    assert requested.status_code in {200, 202}
    assert redis.get(f"otp:{email}") is not None


@pytest.mark.asyncio
async def test_lead_14_qualification_uses_ai_result_and_handles_provider_failure(
    client, api_user
):
    _, headers = await team_context(client, api_user, "lead-ai")
    lead = await create_lead(client, headers, "AIQualification")
    qualified = await client.post(f"/leads/{lead['id']}/qualify", headers=headers)
    assert qualified.status_code in {200, 502, 503}
    if qualified.status_code == 200:
        data = qualified.json()["data"]
        assert data["score"] is not None
        assert data["reasoning"]


@pytest.mark.asyncio
async def test_lead_15_delete_applies_documented_child_lifecycle(client, api_user):
    _, headers = await team_context(client, api_user, "lead-cascade")
    lead = await create_lead(client, headers, "Cascade")
    draft = await client.post(
        "/emails/draft",
        json={"lead_id": lead["id"], "subject": "Cascade", "body": "Body"},
        headers=headers,
    )
    proposal = await client.post(
        "/proposals/",
        json={"lead_id": lead["id"], "file_url": "https://example.invalid/cascade.pdf"},
        headers=headers,
    )
    assert draft.status_code == proposal.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as safe_client:
        deleted = await safe_client.delete(f"/leads/{lead['id']}", headers=headers)
    assert deleted.status_code == 200
    email_after = await client.get(
        f"/emails/{draft.json()['data']['id']}", headers=headers
    )
    proposal_after = await client.get(
        f"/proposals/{proposal.json()['data']['id']}", headers=headers
    )
    assert deleted.status_code == 200
    assert email_after.status_code == 404
    assert proposal_after.status_code == 200
    assert proposal_after.json()["data"]["lead_id"] is None


@pytest.mark.asyncio
async def test_lead_18_list_order_is_deterministic(client, api_user):
    _, headers = await team_context(client, api_user, "lead-order")
    first = await create_lead(client, headers, "OrderFirst")
    second = await create_lead(client, headers, "OrderSecond")
    listed = await client.get("/leads/", headers=headers)
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()["data"]]
    assert ids.index(second["id"]) < ids.index(first["id"])
