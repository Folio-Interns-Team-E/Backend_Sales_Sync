import logging
from upstash_redis import Redis
from redis import Redis as NativeRedis
from app.config import settings

logger = logging.getLogger(__name__)

_redis: Redis | NativeRedis | None = None


def get_redis() -> Redis | NativeRedis | None:
    global _redis
    if _redis is not None:
        return _redis
    if settings.redis_url:
        _redis = NativeRedis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=5, socket_timeout=5,
        )
        return _redis
    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        logger.warning("Upstash Redis not configured — caching disabled")
        _redis = None
        return None
    try:
        _redis = Redis(
            url=settings.upstash_redis_rest_url,
            token=settings.upstash_redis_rest_token,
        )
        logger.info("Upstash Redis connected")
    except Exception as e:
        logger.warning(f"Failed to connect to Upstash Redis: {e}")
        _redis = None
    return _redis
