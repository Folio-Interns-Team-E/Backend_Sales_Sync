from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI, Response
from pydantic import ValidationError

from app.config import Settings, settings
from app.database import get_db
from app.routers.auth import router, _set_refresh_cookie, _clear_refresh_cookie


@pytest.mark.parametrize("path", ["login", "refresh", "logout", "password/request", "password/reset", "otp/request", "register"])
async def test_auth_routes_reject_cross_site_requests_before_database_access(path):
    app = FastAPI()
    app.include_router(router)

    async def no_database():
        pytest.fail("CSRF requests must be rejected before opening a database session")

    app.dependency_overrides[get_db] = no_database
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        for headers in ({}, {"Origin": "https://attacker.example", "X-SalesSync-Request": "1"}, {"Origin": "null", "X-SalesSync-Request": "1"}):
            response = await client.post("/auth/" + path, headers=headers, json={})
            assert response.status_code == 403


async def test_trusted_origin_and_native_client_can_logout():
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        for origin in (None, settings.frontend_origins[0]):
            headers = {"X-SalesSync-Request": "1"}
            if origin:
                headers["Origin"] = origin
            response = await client.post("/auth/logout", headers=headers)
            assert response.status_code == 204


def test_refresh_cookie_works_through_api_prefix_and_is_removed_on_logout():
    response = Response()
    _set_refresh_cookie(response, "test-token")
    cookie = response.headers.getlist("set-cookie")[-1]
    assert "Path=/;" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=604800" in cookie
    response = Response()
    _clear_refresh_cookie(response)
    cookies = response.headers.getlist("set-cookie")
    assert all("Max-Age=0" in value for value in cookies)
    assert any("Path=/auth" in value for value in cookies)
    assert any("Path=/;" in value for value in cookies)


def test_cross_site_cookie_is_secure_in_production():
    with patch.object(settings, "app_env", "production"), patch.object(settings, "refresh_cookie_samesite", "none"):
        response = Response()
        _set_refresh_cookie(response, "test-token")
    cookie = response.headers.getlist("set-cookie")[-1]
    assert "Secure" in cookie and "SameSite=none" in cookie and "HttpOnly" in cookie


def test_cross_site_cookie_rejected_for_http_development():
    with pytest.raises(ValidationError, match="requires HTTPS"):
        Settings(_env_file=None, database_url="postgresql://localhost/test", jwt_secret="test", app_env="development", refresh_cookie_samesite="none")
