from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models.calcom_credentials import CalComIntegration
from sqlalchemy import select


async def context(client, api_user, prefix):
    user = await api_user(prefix)
    team = await client.post("/teams/", json={"name": f"{prefix} Team"}, headers=user["headers"])
    assert team.status_code == 201, team.text
    team_id = team.json()["data"]["id"]
    return user, team_id, {**user["headers"], "X-Team-Id": team_id}


@pytest.mark.asyncio
async def test_mail_16_gmail_auth_url_binds_to_current_user(client, api_user):
    user = await api_user("gmail-url")
    response = await client.get("/integrations/gmail/auth-url", headers=user["headers"])
    assert response.status_code == 200
    url = response.json()["data"]["url"]
    query = parse_qs(urlparse(url).query)
    assert query["state"] == [user["id"]]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


@pytest.mark.asyncio
async def test_mail_16_gmail_status_defaults_disconnected(client, api_user):
    user = await api_user("gmail-status")
    response = await client.get("/integrations/gmail/status", headers=user["headers"])
    assert response.status_code == 200
    assert response.json()["data"] == {"connected": False, "email": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["invalid", "", "not-a-uuid"])
async def test_mail_17_callback_rejects_malformed_state(client, state):
    response = await client.get(
        "/integrations/gmail/callback", params={"code": "test-code", "state": state}
    )
    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_mail_17_callback_cannot_attach_credentials_using_public_user_id(
    client, api_user, monkeypatch
):
    victim = await api_user("oauth-victim")

    async def fake_exchange(code):
        return {
            "refresh_token": "test-only-refresh-token",
            "email": "attacker@example.invalid",
        }

    monkeypatch.setattr("app.routers.integrations.exchange_authorization_code", fake_exchange)
    response = await client.get(
        "/integrations/gmail/callback",
        params={"code": "attacker-code", "state": victim["id"]},
    )
    assert response.status_code in {400, 401, 403}


@pytest.mark.asyncio
async def test_meet_11_calcom_credentials_are_encrypted_and_not_returned(client, api_user):
    user = await api_user("calcom-save")
    response = await client.post(
        "/integrations/calcom",
        json={"cal_api_key": "test-secret-cal-key", "cal_event_type_id": "12345"},
        headers=user["headers"],
    )
    assert response.status_code == 200, response.text
    assert "test-secret-cal-key" not in response.text
    async with SessionLocal() as db:
        result = await db.execute(
            select(CalComIntegration).where(CalComIntegration.user_id == user["id"])
        )
        stored = result.scalar_one()
        assert stored.encrypted_api_key != "test-secret-cal-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"cal_api_key": "", "cal_event_type_id": "123"},
        {"cal_api_key": " ", "cal_event_type_id": "123"},
        {"cal_api_key": "key", "cal_event_type_id": ""},
        {"cal_api_key": "key", "cal_event_type_id": "not-a-number"},
    ],
)
async def test_meet_12_invalid_calcom_configuration_is_rejected(client, api_user, payload):
    user = await api_user("calcom-invalid")
    response = await client.post(
        "/integrations/calcom", json=payload, headers=user["headers"]
    )
    assert response.status_code == 422


async def proposal(client, headers, suffix):
    response = await client.post(
        "/proposals/",
        json={"file_url": f"https://example.invalid/{suffix}.pdf"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_prop_08_status_updates_set_timestamps(client, api_user):
    _, _, headers = await context(client, api_user, "proposal-time")
    item = await proposal(client, headers, "timestamps")
    sent = await client.patch(
        f"/proposals/{item['id']}/status", json={"status": "Sent"}, headers=headers
    )
    accepted = await client.patch(
        f"/proposals/{item['id']}/status", json={"status": "Accepted"}, headers=headers
    )
    assert sent.status_code == accepted.status_code == 200
    assert sent.json()["data"]["sent_at"] is not None
    assert accepted.json()["data"]["responded_at"] is not None


@pytest.mark.asyncio
async def test_prop_11_delete_preserves_unrelated_proposal(client, api_user):
    _, _, headers = await context(client, api_user, "proposal-delete")
    first = await proposal(client, headers, "first")
    second = await proposal(client, headers, "second")
    deleted = await client.delete(f"/proposals/{first['id']}", headers=headers)
    remaining = await client.get(f"/proposals/{second['id']}", headers=headers)
    missing = await client.get(f"/proposals/{first['id']}", headers=headers)
    assert deleted.status_code == remaining.status_code == 200
    assert missing.status_code == 404
