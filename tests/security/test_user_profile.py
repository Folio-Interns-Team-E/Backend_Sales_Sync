from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.routers.auth import get_profile, update_profile
from app.schemas.auth import ProfileUpdate


def user():
    return SimpleNamespace(id=uuid4(), full_name="Alex", email="alex@example.com", company=None, job_title=None)


@pytest.mark.asyncio
async def test_profile_update_is_persisted_for_authenticated_user():
    current_user = user()
    db = SimpleNamespace(commit=AsyncMock())
    payload = ProfileUpdate(full_name=" Alex Smith ", company=" Acme ", job_title=" VP Sales ")
    response = await update_profile(payload, Response(), current_user, db, authorization="Bearer token")
    assert response.data.full_name == "Alex Smith"
    assert response.data.company == "Acme"
    assert response.data.job_title == "VP Sales"
    assert response.data.email == "alex@example.com"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_update_rejects_api_key_only_request():
    db = SimpleNamespace(commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await update_profile(ProfileUpdate(full_name="Alex"), Response(), user(), db, authorization=None)
    assert error.value.status_code == 403
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_read_does_not_return_password_or_session_fields():
    current_user = user()
    current_user.hashed_password = "secret"
    current_user.session_version = 8
    response = await get_profile(Response(), current_user)
    assert response.data.model_dump() == {
        "full_name": "Alex",
        "email": "alex@example.com",
        "company": None,
        "job_title": None,
    }


def test_profile_name_cannot_be_blank():
    with pytest.raises(ValidationError):
        ProfileUpdate(full_name="  ")


def test_profile_update_cannot_change_email():
    with pytest.raises(ValidationError):
        ProfileUpdate(full_name="Alex", email="other@example.com")
