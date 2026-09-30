from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings

#password hashing
import logging
# This forces passlib to ignore the bcrypt version checks and just use it
logging.getLogger("passlib").setLevel(logging.ERROR)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#jwt config
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

def ensure_bcrypt_password_size(password: str) -> None:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password cannot be longer than 72 bytes.")

def hash_password(password: str) -> str:
    ensure_bcrypt_password_size(password)
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    ensure_bcrypt_password_size(plain_password)
    return pwd_context.verify(plain_password, hashed_password)

def _create_token(data: dict, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **data,
        "type": token_type,
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + expires_delta,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(
        data,
        "access",
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(
        data,
        "refresh",
        expires_delta or timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES),
    )


def _decode_token(token: str, expected_type: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
        if payload.get("type") != expected_type or not payload.get("jti"):
            return None
        return payload
    except JWTError:
        return None

def decode_access_token(token: str) -> Optional[dict]:
    return _decode_token(token, "access")


def decode_refresh_token(token: str) -> Optional[dict]:
    return _decode_token(token, "refresh")


def token_is_revoked(payload: dict) -> bool:
    from app.core.redis import get_redis

    redis = get_redis()
    jti = payload.get("jti")
    if not redis or not jti:
        return False
    return bool(redis.get(f"blocklist:{jti}"))


def revoke_token(payload: dict) -> bool:
    from app.core.redis import get_redis

    redis = get_redis()
    jti = payload.get("jti")
    expires_at = payload.get("exp")
    if not jti or not expires_at:
        return False
    if not redis:
        return True
    ttl_seconds = int(expires_at - datetime.now(timezone.utc).timestamp())
    if ttl_seconds <= 0:
        return False
    return bool(
        redis.set(
            f"blocklist:{jti}",
            "revoked",
            ex=ttl_seconds,
            nx=True,
        )
    )
