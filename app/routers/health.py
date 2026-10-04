import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.redis import get_redis
from app.database import engine

router = APIRouter(tags=["health"])


async def check_database():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        # Catch missing tables needed for authentication before routing traffic.
        await connection.execute(text("SELECT id FROM users LIMIT 0"))
        await connection.execute(text("SELECT subject FROM oauth_identities LIMIT 0"))
        await connection.execute(text("SELECT id FROM security_events LIMIT 0"))


async def check_redis():
    client = get_redis()
    if client is None:
        raise RuntimeError("Redis is not configured")
    result = await asyncio.to_thread(client.ping)
    if not result:
        raise RuntimeError("Redis did not respond")


@router.get("/ready")
async def readiness():
    results = await asyncio.gather(
        asyncio.wait_for(check_database(), timeout=5),
        asyncio.wait_for(check_redis(), timeout=5),
        return_exceptions=True,
    )
    checks = {name: not isinstance(result, BaseException) for name, result in zip(("database", "redis"), results)}
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"success": ready, "data": checks},
        headers={"Cache-Control": "no-store"},
    )
