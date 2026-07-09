import logging
from fastapi import Request, HTTPException, status
from upstash_ratelimit import Ratelimit, SlidingWindow
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_ratelimit: Ratelimit | None = None


def _get_ratelimit() -> Ratelimit | None:
    global _ratelimit
    if _ratelimit is not None:
        return _ratelimit
    r = get_redis()
    if r is None:
        logger.warning("Upstash Redis not configured — rate limiting disabled")
        return None
    try:
        _ratelimit = Ratelimit(
            redis=r,
            limiter=SlidingWindow(max=120, duration=60),
        )
        logger.info("Rate limiter initialized: 60 requests per 60 seconds")
    except Exception as e:
        logger.warning(f"Failed to initialize rate limiter: {e}")
        _ratelimit = None
    return _ratelimit


async def rate_limit(request: Request):
    rl = _get_ratelimit()
    if rl is None:
        return

    key = request.client.host if request.client else "unknown"
    result = await rl.limit_async(key)

    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
            headers={
                "Retry-After": str(result.reset),
                "X-RateLimit-Limit": str(rl._limiter.max),
                "X-RateLimit-Remaining": str(result.remaining),
            },
        )
