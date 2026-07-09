import json
import logging
from typing import Any, Optional
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 300


def cache_key(*parts: str) -> str:
    return ":".join(str(p) for p in parts)


def cache_get(key: str) -> Optional[Any]:
    r = get_redis()
    if r is None:
        return None
    try:
        data = r.get(key)
        if data is None:
            return None
        return json.loads(data)
    except Exception as e:
        logger.warning(f"Cache GET error for key '{key}': {e}")
        return None


def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        data = json.dumps(value, default=str)
        r.setex(key, ttl, data)
    except Exception as e:
        logger.warning(f"Cache SET error for key '{key}': {e}")


def cache_delete(key: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception as e:
        logger.warning(f"Cache DELETE error for key '{key}': {e}")


def cache_invalidate(pattern: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        cursor = 0
        while True:
            result = r.scan(cursor=cursor, match=pattern, count=100)
            cursor = result[0]
            keys = result[1]
            if keys:
                r.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"Cache INVALIDATE error for pattern '{pattern}': {e}")
