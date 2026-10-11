import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.redis import get_redis
from app.core.worker_health import sequence_worker_is_healthy
from app.database import engine

router = APIRouter(tags=["health"])
MIGRATION_CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"


def expected_migration_heads() -> set[str]:
    config = Config(str(MIGRATION_CONFIG))
    config.set_main_option("script_location", str(MIGRATION_CONFIG.parent / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def check_database():
    async with engine.connect() as connection:
        # LIMIT 0 validates required tables and columns without reading data.
        # Keep this in one round trip: Railway and Neon may be far apart.
        await connection.execute(text("""
            SELECT u.id, u.company, u.job_title, u.session_version,
                   oi.subject, se.id, ae.id, sne.id, sne.reply_override,
                   n.id, wak.id, gc.encrypted_refresh_token,
                   ci.encrypted_access_token
            FROM users AS u, oauth_identities AS oi, security_events AS se,
                 audit_events AS ae, sequence_enrollments AS sne,
                 notifications AS n, workspace_api_keys AS wak,
                 google_credentials AS gc, calcom_integrations AS ci
            LIMIT 0
        """))
        versions = await connection.execute(text("SELECT version_num FROM alembic_version"))
        if set(versions.scalars().all()) != expected_migration_heads():
            raise RuntimeError("Database migrations are not at the deployed revision")


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
        asyncio.wait_for(check_database(), timeout=20),
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


@router.get("/ready/sequence-worker")
async def sequence_worker_readiness():
    try:
        healthy = await asyncio.wait_for(sequence_worker_is_healthy(), timeout=5)
    except Exception:
        healthy = False
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"success": healthy, "data": {"sequence_worker": healthy}},
        headers={"Cache-Control": "no-store"},
    )
