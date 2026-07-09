import logging
from upstash_redis import Redis
from app.config import settings

logger = logging.getLogger(__name__)

_redis: Redis | None = None


def get_redis() -> Redis | None:
    global _redis
    if _redis is not None:
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
