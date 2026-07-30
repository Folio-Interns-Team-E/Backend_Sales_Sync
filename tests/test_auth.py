from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.security import (
    create_access_token,
    ensure_bcrypt_password_size,
    hash_password,
    verify_password,
)


@pytest.mark.asyncio
async def test_auth_01_registers_user_and_requires_verification(client, unique_email):
    response = await client.post(
        "/auth/register",
        json={
            "full_name": "Auth Test User",
            "email": unique_email("register"),
            "password": "SafePassword123!",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["needs_verification"] is True
    assert body["data"]["user_id"]


@pytest.mark.asyncio
async def test_auth_02_duplicate_email_is_case_insensitive(client, unique_email):
    email = unique_email("duplicate")
    payload = {
        "full_name": "Duplicate User",
        "email": email,
        "password": "SafePassword123!",
    }
    assert (await client.post("/auth/register", json=payload)).status_code == 201

    duplicate = await client.post(
        "/auth/register",
        json={**payload, "email": email.upper()},
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_auth_03_malformed_email_is_rejected(client):
    response = await client.post(
        "/auth/register",
        json={
            "full_name": "Invalid Email",
            "email": "not-an-email",
            "password": "SafePassword123!",
        },
    )
    assert response.status_code == 422
    assert response.json()["success"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", " ", "\t"])
async def test_auth_04_blank_name_is_rejected(client, unique_email, name):
    response = await client.post(
        "/auth/register",
        json={
            "full_name": name,
            "email": unique_email("blank-name"),
            "password": "SafePassword123!",
        },
    )
    assert response.status_code == 400


def test_auth_05_bcrypt_boundary_handles_multibyte_passwords():
    exactly_72 = "a" * 72
    ensure_bcrypt_password_size(exactly_72)
    digest = hash_password(exactly_72)
    assert verify_password(exactly_72, digest)

    with pytest.raises(ValueError, match="72 bytes"):
        ensure_bcrypt_password_size("é" * 37)


@pytest.mark.asyncio
async def test_auth_09_unknown_and_wrong_password_use_same_response(client, api_user, unique_email):
    known = await api_user("enumeration")
    unknown = await client.post(
        "/auth/login",
        json={"email": unique_email("unknown"), "password": known["password"]},
    )
    wrong = await client.post(
        "/auth/login",
        json={"email": known["email"], "password": "WrongPassword123!"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"] == wrong.json()["error"]


@pytest.mark.asyncio
async def test_auth_10_unverified_login_returns_no_token(client, api_user):
    user = await api_user("unverified")
    response = await client.post(
        "/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["needs_verification"] is True
    assert data["access_token"] is None


@pytest.mark.asyncio
async def test_auth_18_protected_route_rejects_invalid_jwts(client, api_user):
    user = await api_user("jwt")
    cases = [
        None,
        "not-a-jwt",
        create_access_token({}, expires_delta=timedelta(minutes=5)),
        create_access_token({"sub": "not-a-uuid"}, expires_delta=timedelta(minutes=5)),
        create_access_token({"sub": user["id"]}, expires_delta=timedelta(seconds=-1)),
    ]

    for token in cases:
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        response = await client.get("/teams/", headers=headers)
        assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_auth_20_logout_returns_204(client):
    response = await client.post("/auth/logout")
    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_core_09_malformed_json_is_controlled_4xx(client):
    response = await client.post(
        "/auth/login",
        content=b'{"email":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["success"] is False
