from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/salessync_e2e"
)
os.environ["JWT_SECRET"] = "e2e-only-jwt-secret-do-not-use-outside-tests"
os.environ["FRONTEND_ORIGINS"] = '["http://127.0.0.1:5173"]'
os.environ["DB_ENCRYPTION_KEY"] = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
os.environ["FROM_EMAIL"] = "e2e@example.invalid"
os.environ["UPSTASH_REDIS_REST_URL"] = ""
os.environ["UPSTASH_REDIS_REST_TOKEN"] = ""
os.environ["RESEND_API_KEY"] = ""
os.environ["GROK_API_KEY"] = ""
os.environ["PINECONE_API_KEY"] = ""
os.environ["AWS_ACCESS_KEY_ID"] = ""
os.environ["AWS_SECRET_ACCESS_KEY"] = ""
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""

from app.core.security import create_access_token  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def initialize_test_schema() -> AsyncIterator[None]:
    database_url = os.environ["DATABASE_URL"]
    if "salessync_e2e" not in database_url or ":5433/" not in database_url:
        raise RuntimeError("Tests refuse to run outside the isolated E2E database")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.fixture
def unique_email():
    def factory(prefix: str = "user") -> str:
        return f"{prefix}-{uuid4().hex}@example.com"

    return factory


@pytest_asyncio.fixture
async def api_user(client: AsyncClient, unique_email):
    async def factory(prefix: str = "user", password: str = "SafePassword123!"):
        email = unique_email(prefix)
        response = await client.post(
            "/auth/register",
            json={
                "full_name": f"{prefix.title()} Test User",
                "email": email,
                "password": password,
            },
        )
        assert response.status_code == 201, response.text
        user_id = response.json()["data"]["user_id"]
        token = create_access_token({"sub": user_id})
        return {
            "id": user_id,
            "email": email,
            "password": password,
            "token": token,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    return factory
