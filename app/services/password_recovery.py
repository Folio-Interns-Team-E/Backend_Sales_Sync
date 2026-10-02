"""Expiring, single-use password recovery credentials stored only as digests."""
import hashlib
import json
import secrets
from uuid import UUID

import resend
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.config import settings
from app.core.redis import get_redis
from app.core.security import hash_password, session_claims, session_matches_user
from app.models.user import User

RESET_TTL = 15 * 60


def _redis():
    client = get_redis()
    if client is None:
        raise HTTPException(503, "Password recovery is temporarily unavailable.")
    return client


def _key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def send_reset_email(email: str, token: str):
    resend.Emails.send({
        "from": settings.FROM_EMAIL,
        "to": [email],
        "subject": "Reset your SalesSync password",
        "text": f"Enter this recovery code on the SalesSync password recovery page:\n\n{token}\n\n"
                "It expires in 15 minutes and can be used once. If you did not request this, ignore this email.",
    })


async def request_reset(email: str, client_ip: str, tasks: BackgroundTasks, db):
    client = _redis()
    ip_key = "reset_ip:" + _key(client_ip)
    attempts = client.incr(ip_key)
    if attempts == 1:
        client.expire(ip_key, RESET_TTL)
    if attempts > 10:
        raise HTTPException(429, "Too many requests. Please try again later.")
    if not client.set("reset_cooldown:" + _key(email.lower()), "1", nx=True, ex=60):
        return
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return
    token = secrets.token_urlsafe(32)
    client.set("password_reset:" + _key(token), json.dumps(session_claims(user)), ex=RESET_TTL)
    tasks.add_task(send_reset_email, user.email, token)


async def confirm_reset(token: str, password: str, db):
    client = _redis()
    # Atomically consume the credential, including concurrent requests.
    stored = client.getdel("password_reset:" + _key(token))
    if not stored:
        raise HTTPException(400, "Invalid or expired recovery code. Request a new code.")
    claims = json.loads(stored)
    result = await db.execute(select(User).where(User.id == UUID(claims["sub"])).with_for_update())
    user = result.scalar_one_or_none()
    if user is None or not session_matches_user(claims, user):
        raise HTTPException(400, "Invalid or expired recovery code. Request a new code.")
    user.hashed_password = hash_password(password)
    await db.commit()
