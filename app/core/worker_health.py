import asyncio

from app.core.redis import get_redis

SEQUENCE_WORKER_HEARTBEAT_KEY = "health:sequence-worker:last-success"


async def record_sequence_worker_heartbeat(interval_seconds: int) -> None:
    redis = get_redis()
    if redis is None:
        raise RuntimeError("Redis is not configured")
    await asyncio.to_thread(
        redis.set,
        SEQUENCE_WORKER_HEARTBEAT_KEY,
        "ok",
        ex=max(60, interval_seconds * 3 + 30),
    )


async def sequence_worker_is_healthy() -> bool:
    redis = get_redis()
    if redis is None:
        return False
    return bool(await asyncio.to_thread(redis.get, SEQUENCE_WORKER_HEARTBEAT_KEY))
