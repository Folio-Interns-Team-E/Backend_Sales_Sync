from __future__ import annotations

from uuid import uuid4

import pytest


async def make_context(client, api_user, prefix):
    user = await api_user(prefix)
    team = await client.post("/teams/", json={"name": f"{prefix} Team"}, headers=user["headers"])
    assert team.status_code == 201, team.text
    headers = {**user["headers"], "X-Team-Id": team.json()["data"]["id"]}
    lead = await client.post(
        "/leads/",
        json={
            "name": f"{prefix} Lead",
            "email": f"{prefix}-{uuid4().hex}@example.com",
        },
        headers=headers,
    )
    assert lead.status_code == 201, lead.text
    return user, headers, lead.json()["data"]


async def make_draft(client, headers, lead_id, subject="Draft subject"):
    response = await client.post(
        "/emails/draft",
        json={"lead_id": lead_id, "subject": subject, "body": "Draft body"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_mail_03_save_draft_persists_and_appears_in_history(client, api_user):
    _, headers, lead = await make_context(client, api_user, "mail-draft")
    draft = await make_draft(client, headers, lead["id"])
    history = await client.get(f"/emails/?lead_id={lead['id']}", headers=headers)
    assert history.status_code == 200
    assert draft["id"] in {item["id"] for item in history.json()["data"]}
    assert draft["status"] == "draft"


@pytest.mark.asyncio
async def test_mail_04_missing_and_cross_team_leads_are_denied(client, api_user):
    _, headers, _ = await make_context(client, api_user, "mail-owner")
    _, other_headers, other_lead = await make_context(client, api_user, "mail-other")
    missing = await client.post(
        "/emails/draft",
        json={"lead_id": str(uuid4()), "subject": "No lead", "body": "Body"},
        headers=headers,
    )
    cross_team = await client.post(
        "/emails/draft",
        json={"lead_id": other_lead["id"], "subject": "Private", "body": "Body"},
        headers=headers,
    )
    assert missing.status_code in {403, 404}
    assert cross_team.status_code in {403, 404}


@pytest.mark.asyncio
async def test_mail_08_disconnected_gmail_does_not_mark_email_sent(client, api_user):
    _, headers, lead = await make_context(client, api_user, "mail-disconnected")
    response = await client.post(
        "/emails/",
        json={"lead_id": lead["id"], "subject": "Send", "body": "Body"},
        headers=headers,
    )
    assert response.status_code in {400, 409, 422, 503}
    history = await client.get(f"/emails/?lead_id={lead['id']}", headers=headers)
    assert all(item["status"] != "sent" for item in history.json()["data"])


@pytest.mark.asyncio
async def test_mail_12_list_all_and_filter_by_lead(client, api_user):
    _, headers, first = await make_context(client, api_user, "mail-list")
    second_response = await client.post(
        "/leads/",
        json={"name": "Second", "email": f"second-{uuid4().hex}@example.com"},
        headers=headers,
    )
    second = second_response.json()["data"]
    first_draft = await make_draft(client, headers, first["id"], "First")
    second_draft = await make_draft(client, headers, second["id"], "Second")

    all_emails = await client.get("/emails/", headers=headers)
    filtered = await client.get(f"/emails/?lead_id={first['id']}", headers=headers)
    assert all_emails.status_code == filtered.status_code == 200
    assert {first_draft["id"], second_draft["id"]}.issubset(
        {item["id"] for item in all_emails.json()["data"]}
    )
    assert {item["id"] for item in filtered.json()["data"]} == {first_draft["id"]}


@pytest.mark.asyncio
async def test_mail_13_get_patch_delete_draft(client, api_user):
    _, headers, lead = await make_context(client, api_user, "mail-crud")
    draft = await make_draft(client, headers, lead["id"])
    fetched = await client.get(f"/emails/{draft['id']}", headers=headers)
    updated = await client.patch(
        f"/emails/{draft['id']}",
        json={"subject": "Updated", "body": "Updated body"},
        headers=headers,
    )
    deleted = await client.delete(f"/emails/{draft['id']}", headers=headers)
    missing = await client.get(f"/emails/{draft['id']}", headers=headers)
    assert fetched.status_code == updated.status_code == deleted.status_code == 200
    assert updated.json()["data"]["subject"] == "Updated"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_mail_14_sent_email_is_immutable(client, api_user, monkeypatch):
    _, headers, lead = await make_context(client, api_user, "mail-sent")

    async def sent(*args, **kwargs):
        return None

    monkeypatch.setattr("app.routers.emails.send_email_in_background", sent)
    created = await client.post(
        "/emails/",
        json={"lead_id": lead["id"], "subject": "Sent", "body": "Audit body"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    email_id = created.json()["data"]["id"]
    patched = await client.patch(
        f"/emails/{email_id}", json={"subject": "Tampered"}, headers=headers
    )
    deleted = await client.delete(f"/emails/{email_id}", headers=headers)
    assert patched.status_code == deleted.status_code == 400


@pytest.mark.asyncio
async def test_mail_cross_team_email_crud_is_denied(client, api_user):
    _, owner_headers, lead = await make_context(client, api_user, "mail-private")
    _, stranger_headers, _ = await make_context(client, api_user, "mail-stranger")
    draft = await make_draft(client, owner_headers, lead["id"])
    responses = [
        await client.get(f"/emails/{draft['id']}", headers=stranger_headers),
        await client.patch(
            f"/emails/{draft['id']}", json={"subject": "Stolen"}, headers=stranger_headers
        ),
        await client.delete(f"/emails/{draft['id']}", headers=stranger_headers),
    ]
    assert all(response.status_code in {403, 404} for response in responses)


@pytest.mark.asyncio
async def test_mail_15_rejects_header_injection(client, api_user):
    _, headers, lead = await make_context(client, api_user, "mail-injection")
    response = await client.post(
        "/emails/draft",
        json={
            "lead_id": lead["id"],
            "subject": "Hello\r\nBcc: victim@example.com",
            "body": "<script>alert('x')</script>",
        },
        headers=headers,
    )
    assert response.status_code in {400, 422}
