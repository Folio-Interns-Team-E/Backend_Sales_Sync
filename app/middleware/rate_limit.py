"""Redis-backed request rate limiting for costly and security-sensitive actions."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request, Response

from app.config import settings
from app.core.redis import get_redis
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)

RateLimitScope = Literal["ip", "user", "team"]


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int


AUTH_LOGIN = RateLimitPolicy("auth-login", 10, 60)
AUTH_REGISTER = RateLimitPolicy("auth-register", 5, 60 * 60)
AUTH_OTP = RateLimitPolicy("auth-otp", 5, 15 * 60)
AUTH_PASSWORD_RESET = RateLimitPolicy("auth-password-reset", 5, 15 * 60)
AUTH_REFRESH = RateLimitPolicy("auth-refresh", 30, 60)
OAUTH_FLOW = RateLimitPolicy("oauth-flow", 20, 5 * 60)
AI_CHAT = RateLimitPolicy("ai-chat", 30, 60)
EMAIL_SEND = RateLimitPolicy("email-send", 30, 60)
EMAIL_DRAFT = RateLimitPolicy("email-draft", 60, 60)
LEAD_DISCOVERY = RateLimitPolicy("lead-discovery", 20, 60 * 60)
LEAD_IMPORT = RateLimitPolicy("lead-import", 10, 60 * 60)


def _client_ip(request: Request) -> str:
    if settings.rate_limit_trust_proxy_headers:
        cloudflare_ip = request.headers.get("cf-connecting-ip")
        if cloudflare_ip:
            return cloudflare_ip.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _bearer_subject(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    payload = decode_access_token(authorization[7:].strip())
    subject = payload.get("sub") if payload else None
    return str(subject) if subject else None


def _identity(request: Request, scope: RateLimitScope) -> str:
    if scope == "team":
        team_id = request.headers.get("x-team-id")
        if team_id:
            return f"team:{team_id.strip().lower()}"
    elif scope == "user":
        subject = _bearer_subject(request)
        if subject:
            return f"user:{subject}"
    return f"ip:{_client_ip(request)}"


def _key(policy: RateLimitPolicy, scope: RateLimitScope, identity: str, window: int) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"salesync:rate-limit:{policy.name}:{scope}:{digest}:{window}"


async def _redis_call(client, method: str, *args, **kwargs):
    return await asyncio.to_thread(getattr(client, method), *args, **kwargs)


async def _consume(policy: RateLimitPolicy, scope: RateLimitScope, identity: str) -> tuple[int, int]:
    client = get_redis()
    if client is None:
        raise RuntimeError("Redis is not configured")

    now = time.time()
    window = math.floor(now / policy.window_seconds)
    key = _key(policy, scope, identity, window)
    # SET NX establishes an expiry before the counter is incremented, preventing
    # an interrupted first request from leaving a permanent limiter key behind.
    await _redis_call(client, "set", key, 0, nx=True, ex=policy.window_seconds + 1)
    count = int(await _redis_call(client, "incr", key))
    reset_seconds = max(1, math.ceil(((window + 1) * policy.window_seconds) - now))
    return count, reset_seconds


def rate_limit(policy: RateLimitPolicy, *scopes: RateLimitScope):
    """Create a FastAPI dependency that enforces a policy for one or more identities."""

    selected_scopes = scopes or ("ip",)

    async def dependency(request: Request, response: Response) -> None:
        results: list[tuple[int, int]] = []
        try:
            for scope in selected_scopes:
                results.append(await _consume(policy, scope, _identity(request, scope)))
        except Exception as exc:
            if settings.app_env.lower() in {"production", "staging"}:
                logger.exception("Rate-limit storage unavailable for %s", policy.name)
                raise HTTPException(
                    status_code=503,
                    detail="Request protection service is temporarily unavailable",
                    headers={"Retry-After": "30"},
                ) from exc
            logger.warning("Rate limiting skipped for %s: %s", policy.name, exc)
            return

        highest_count = max(count for count, _ in results)
        retry_after = max(reset for _, reset in results)
        remaining = max(0, policy.limit - highest_count)
        response.headers["X-RateLimit-Limit"] = str(policy.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + retry_after)

        if highest_count > policy.limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait before trying again.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(policy.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

    return dependency
