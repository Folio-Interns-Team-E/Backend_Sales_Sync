from __future__ import annotations

import logging
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.email import Email, EmailStatus
from app.models.google_credentials import GoogleCredentials
from app.models.lead import Lead
from app.services import gmail_service
from tests.test_core_resources import create_lead, team_context


async def _mail_context(client, api_user, prefix: str):
    user, headers = await team_context(client, api_user, prefix)
    lead = await create_lead(client, headers, prefix)
    return user, headers, lead


async def _store_google_credentials(user_id: str, token: str = "refresh-secret"):
    async with SessionLocal() as db:
        db.add(
            GoogleCredentials(
                user_id=UUID(user_id),
                google_email="sender@example.com",
                refresh_token=token,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_mail_01_and_07_selected_lead_is_the_only_recipient_and_success_is_persisted(
    client, api_user, monkeypatch
):
    user, headers, lead = await _mail_context(client, api_user, "mail-success")
    await _store_google_credentials(user["id"])
    deliveries = []

    async def delivered(db, user_id, recipient, subject, body):
        deliveries.append((str(user_id), recipient, subject, body))

    monkeypatch.setattr(gmail_service, "send_email_on_behalf_of_user", delivered)
    response = await client.post(
        "/emails/",
        json={
            "lead_id": lead["id"],
            "subject": "Relevant subject",
            "body": "Relevant body",
            "tone": "Professional",
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert deliveries == [
        (user["id"], lead["email"], "Relevant subject", "Relevant body")
    ]
    email = response.json()["data"]
    assert email["status"] == "sent"
    assert email["sent_at"] is not None
    assert email["ai_metadata"]["tone"] == "Professional"
    refreshed_lead = await client.get(f"/leads/{lead['id']}", headers=headers)
    assert refreshed_lead.json()["data"]["status"] == "Sent"


@pytest.mark.asyncio
async def test_mail_09_expired_access_refreshes_once_and_sends_once(
    client, api_user, monkeypatch
):
    user, _, lead = await _mail_context(client, api_user, "mail-refresh")
    await _store_google_credentials(user["id"], "stored-refresh-token")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            if url == gmail_service.GOOGLE_TOKEN_URL:
                return FakeResponse({"access_token": "fresh-access-token"})
            return FakeResponse({"id": "gmail-message-id"})

    monkeypatch.setattr(gmail_service.httpx, "AsyncClient", FakeHttpClient)
    async with SessionLocal() as db:
        await gmail_service.send_email_on_behalf_of_user(
            db,
            UUID(user["id"]),
            lead["email"],
            "Refresh subject",
            "Refresh body",
        )

    token_calls = [call for call in calls if call[0] == gmail_service.GOOGLE_TOKEN_URL]
    send_calls = [call for call in calls if call[0] == gmail_service.GMAIL_SEND_URL]
    assert len(token_calls) == len(send_calls) == 1
    assert token_calls[0][1]["data"]["refresh_token"] == "stored-refresh-token"
    assert send_calls[0][1]["headers"]["Authorization"] == "Bearer fresh-access-token"


@pytest.mark.asyncio
async def test_mail_10_gmail_failure_keeps_email_and_lead_state_truthful(
    client, api_user, monkeypatch
):
    _, headers, lead = await _mail_context(client, api_user, "mail-send-failure")

    async def failed(*args, **kwargs):
        raise httpx.ConnectTimeout("gmail timed out")

    monkeypatch.setattr(gmail_service, "send_email_on_behalf_of_user", failed)
    response = await client.post(
        "/emails/",
        json={"lead_id": lead["id"], "subject": "Subject", "body": "Body"},
        headers=headers,
    )
    history = await client.get(f"/emails/?lead_id={lead['id']}", headers=headers)
    refreshed_lead = await client.get(f"/leads/{lead['id']}", headers=headers)

    assert response.status_code in {502, 503, 504}
    assert all(item["status"] != "sent" for item in history.json()["data"])
    assert refreshed_lead.json()["data"]["status"] != "Sent"


@pytest.mark.asyncio
async def test_mail_11_concurrent_duplicate_requests_deliver_at_most_once(
    client, api_user, monkeypatch
):
    _, headers, lead = await _mail_context(client, api_user, "mail-idempotency")
    deliveries = []

    async def delivered(*args):
        deliveries.append(args)

    monkeypatch.setattr(gmail_service, "send_email_on_behalf_of_user", delivered)
    payload = {"lead_id": lead["id"], "subject": "One subject", "body": "One body"}
    first = await client.post("/emails/", json=payload, headers=headers)
    second = await client.post("/emails/", json=payload, headers=headers)
    history = await client.get(f"/emails/?lead_id={lead['id']}", headers=headers)

    assert first.status_code == 201
    assert second.status_code in {200, 201, 409}
    assert len(deliveries) == 1
    assert len(history.json()["data"]) == 1


@pytest.mark.asyncio
async def test_mail_18_oauth_denial_is_controlled_and_remains_disconnected(
    client, api_user
):
    user = await api_user("mail-oauth-denial")
    denied = await client.get(
        "/integrations/gmail/callback",
        params={
            "error": "access_denied",
            "state": user["id"],
        },
        follow_redirects=False,
    )
    status = await client.get("/integrations/gmail/status", headers=user["headers"])

    assert denied.status_code in {302, 400}
    assert "success" not in denied.headers.get("location", "")
    assert status.status_code == 200
    assert status.json()["data"]["connected"] is False


@pytest.mark.asyncio
async def test_mail_19_credentials_are_absent_from_api_and_redacted_from_logs(
    client, api_user, monkeypatch, caplog
):
    user = await api_user("mail-secrets")
    secret = "refresh-token-must-never-leak"
    await _store_google_credentials(user["id"], secret)

    async def failed_refresh(refresh_token):
        raise RuntimeError(f"provider rejected credential {refresh_token}")

    monkeypatch.setattr(gmail_service, "refresh_access_token", failed_refresh)
    with caplog.at_level(logging.ERROR):
        async with SessionLocal() as db:
            with pytest.raises(RuntimeError):
                await gmail_service.send_email_on_behalf_of_user(
                    db,
                    UUID(user["id"]),
                    "recipient@example.com",
                    "Subject",
                    "Body",
                )

    status = await client.get("/integrations/gmail/status", headers=user["headers"])
    serialized = status.text + caplog.text
    assert status.status_code == 200
    assert status.json()["data"] == {
        "connected": True,
        "email": "sender@example.com",
    }
    assert secret not in serialized
