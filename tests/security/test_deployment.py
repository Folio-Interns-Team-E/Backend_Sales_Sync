import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.database_config import async_database_options
from app.routers import health
from app.serve import server_options


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_railway_database_urls_keep_credentials_and_use_async_driver(scheme):
    url, options = async_database_options(f"{scheme}://user:p%40ss@db.internal:5432/app", environment="production")
    assert url.drivername == "postgresql+asyncpg"
    assert url.password == "p@ss"
    assert url.host == "db.internal"
    assert options == {"ssl": "require"}


def test_database_ssl_query_translated_for_asyncpg():
    url, options = async_database_options("postgresql://db/app?sslmode=verify-full")
    assert "sslmode" not in url.query
    assert options == {"ssl": "verify-full"}


def test_explicit_ssl_setting_takes_priority():
    _, options = async_database_options("postgresql://db/app?sslmode=require", ssl_mode="disable")
    assert options == {"ssl": "disable"}


def test_development_keeps_existing_connection_behavior():
    _, options = async_database_options("postgresql+asyncpg://db/app")
    assert options == {}


def test_container_binds_assigned_port_without_sensitive_access_logs(monkeypatch):
    monkeypatch.setenv("PORT", "4321")
    options = server_options()
    assert options["port"] == 4321
    assert options["host"] == "0.0.0.0"
    assert options["access_log"] is False


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_port_fails_at_startup(monkeypatch, port):
    monkeypatch.setenv("PORT", port)
    with pytest.raises(ValueError):
        server_options()


@pytest.mark.parametrize("database_ok,redis_ok", [(True, True), (True, False), (False, True)])
async def test_readiness_checks_both_dependencies_without_exposing_errors(database_ok, redis_ok):
    with (
        patch.object(health, "check_database", new=AsyncMock(side_effect=None if database_ok else RuntimeError("private database credentials"))),
        patch.object(health, "check_redis", new=AsyncMock(side_effect=None if redis_ok else RuntimeError("private redis token"))),
    ):
        response = await health.readiness()
    assert response.status_code == (200 if database_ok and redis_ok else 503)
    body = json.loads(response.body)
    assert body["data"] == {"database": database_ok, "redis": redis_ok}
    assert b"private" not in response.body


async def test_production_startup_does_not_mutate_schema():
    from app import main
    with patch.object(main.settings, "app_env", "production"), patch.object(main, "engine") as engine:
        await main.startup()
    engine.begin.assert_not_called()
