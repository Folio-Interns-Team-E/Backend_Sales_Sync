import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, FastAPI

from app.core.security import session_claims
from app.database import get_db
from app.routers.social_auth import router
from app.services import social_auth as service


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, **kwargs):
        self.values[key] = value
        assert kwargs == {"ex": 600, "nx": True}
        return True

    def get(self, key):
        return self.values.get(key)

    def getdel(self, key):
        return self.values.pop(key, None)


@pytest.mark.parametrize("provider", ["google", "github"])
def test_browser_bound_state_is_single_use_and_uses_pkce(provider):
    redis = FakeRedis()
    with patch.object(service, "credentials", return_value=("client", "secret")), patch.object(service, "redis_client", return_value=redis), patch.object(service.settings, "frontend_origins", [service.settings.oauth_frontend_url]):
        url, binding = service.begin(provider)
        params = parse_qs(urlsplit(url).query)
        state = params["state"][0]
        assert params["code_challenge_method"] == ["S256"]
        assert "secret" not in url
        with pytest.raises(HTTPException):
            service.consume(provider, state, "different-browser")
        with pytest.raises(HTTPException):
            service.consume("github" if provider == "google" else "google", state, binding)
        record = service.consume(provider, state, binding)
        assert record["provider"] == provider
        assert record["verifier"] not in url
        with pytest.raises(HTTPException):
            service.consume(provider, state, binding)


def result(value):
    return SimpleNamespace(scalar_one_or_none=lambda: value)


async def test_existing_email_does_not_silently_link():
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(None), result(SimpleNamespace(id=uuid4()))]), add=Mock())
    with pytest.raises(HTTPException) as exc:
        await service.resolve_user(db, "google", "subject", "existing@example.com", "Name")
    assert exc.value.status_code == 409
    db.add.assert_not_called()


async def test_linked_subject_signs_in_even_if_provider_email_changes():
    user = SimpleNamespace(id=uuid4(), email_verified=True)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(SimpleNamespace(user_id=user.id)), result(user)]), add=Mock(), commit=AsyncMock())
    assert await service.resolve_user(db, "github", "123", "changed@example.com", "Name") is user
    assert db.add.call_args.args[0].action.value == "github_login"
    db.commit.assert_awaited_once()


async def test_authenticated_link_cannot_take_another_users_identity():
    user = SimpleNamespace(id=uuid4(), email_verified=True, hashed_password="hash")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(SimpleNamespace(user_id=uuid4())), result(user)]))
    with pytest.raises(HTTPException) as exc:
        await service.resolve_user(db, "github", "123", "person@example.com", "Name", session_claims(user))
    assert exc.value.status_code == 409


async def test_new_user_and_identity_are_created_together():
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(None), result(None)]), add=Mock(), flush=AsyncMock(), commit=AsyncMock())
    user = await service.resolve_user(db, "google", "123", "person@example.com", "Person")
    assert user.email_verified is True
    assert user.email == "person@example.com"
    assert db.add.call_count == 3
    assert db.add.call_args.args[0].action.value == "google_login"
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("provider", ["google", "github"])
@pytest.mark.parametrize("verified", [True, False])
async def test_provider_requires_verified_email(provider, verified):
    def handler(request):
        if request.method == "POST":
            assert b"code_verifier=verifier" in request.content
            return httpx.Response(200, json={"access_token": "provider-token"})
        assert request.headers["Authorization"] == "Bearer provider-token"
        if request.url.path == "/user/emails":
            return httpx.Response(200, json=[{"email": "person@example.com", "primary": True, "verified": verified}])
        return httpx.Response(200, json={"id": 123, "sub": "123", "email": "person@example.com", "email_verified": verified})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch.object(service, "credentials", return_value=("client", "secret")), patch.object(service.httpx, "AsyncClient", return_value=client):
        if verified:
            assert (await service.provider_profile(provider, "code", "verifier"))[:2] == ("123", "person@example.com")
        else:
            with pytest.raises(HTTPException):
                await service.provider_profile(provider, "code", "verifier")


async def test_callback_sets_httponly_session_without_token_in_redirect():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    user = SimpleNamespace(id=uuid4(), hashed_password="hash")
    with (
        patch.object(service, "consume", return_value={"verifier": "verifier", "link": None}),
        patch.object(service, "provider_profile", new=AsyncMock(return_value=("123", "person@example.com", "Person"))),
        patch.object(service, "resolve_user", new=AsyncMock(return_value=user)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
            response = await client.get("/auth/oauth/google/callback?state=test&code=test")
    assert response.status_code == 303
    assert response.headers["location"].endswith("/dashboard")
    assert "token" not in response.headers["location"]
    assert any("refresh_token=" in cookie and "HttpOnly" in cookie for cookie in response.headers.get_list("set-cookie"))
    assert response.headers["Cache-Control"] == "no-store"


async def test_start_requires_csrf_header():
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        response = await client.post("/auth/oauth/google/start")
    assert response.status_code == 403
