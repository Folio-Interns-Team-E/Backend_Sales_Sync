from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
import asyncio
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RegisterResponse, LoginResponse
from app.core.security import (
    create_access_token,
    create_refresh_token,
    ensure_bcrypt_password_size,
    hash_password,
    verify_password,
    session_claims,
)
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from app.schemas.auth import OTPRequest, OTPVerifyRequest
from app.core.redis import get_redis
from app.services.security_activity import record_security_event
from app.models.security_event import SecurityAction

import resend

from app.config import settings

logger = logging.getLogger(__name__)

OTP_EXPIRY_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_REQUEST_COOLDOWN_SECONDS = 60
LOGIN_MAX_ATTEMPTS = 10
LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60
DUMMY_PASSWORD_HASH = "$2b$12$rWwzGgt1Al3V6a79qCLsFuOO6.ljkwDjkCNiANyXzwg6aW.p07b1u"


class EmailDeliveryError(RuntimeError):
    """Raised when a verification email cannot be accepted for delivery."""


def _email_sender() -> str:
    api_key = settings.RESEND_API_KEY.strip()
    sender = settings.FROM_EMAIL.strip()
    if not api_key or not sender or "\r" in sender or "\n" in sender:
        raise EmailDeliveryError("Email delivery is not configured.")
    resend.api_key = api_key
    return sender


def _verification_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Verification email could not be sent. Please try again later.",
    )


def _otp_digest(otp: str) -> str:
    return hmac.new(
        settings.jwt_secret.encode(),
        otp.encode(),
        hashlib.sha256,
    ).hexdigest()


def _login_attempt_key(email: str, client_ip: str) -> str:
    identity = f"{email.strip().lower()}:{client_ip}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"login_attempts:{digest}"


def _record_failed_login(redis_client, key: str) -> None:
    if not redis_client:
        return
    attempts = redis_client.incr(key)
    if attempts == 1:
        redis_client.expire(key, LOGIN_ATTEMPT_WINDOW_SECONDS)


async def register_user(payload: RegisterRequest, db: AsyncSession) -> RegisterResponse:
    if not payload.full_name or not payload.full_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name is required."
        )

    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long."
        )

    try:
        ensure_bcrypt_password_size(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Try logging in instead."
        )

    new_user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )

    redis_client = get_redis()
    if not redis_client:
        raise _verification_unavailable()

    otp_key = f"otp:{new_user.email}"
    otp = generate_six_digit_otp()
    db.add(new_user)
    try:
        await db.flush()
        redis_client.set(otp_key, _otp_digest(otp), ex=OTP_EXPIRY_SECONDS)
        await send_otp_email(new_user.email, otp)
        await db.commit()
        await db.refresh(new_user)
    except EmailDeliveryError as exc:
        await db.rollback()
        try:
            redis_client.delete(otp_key)
        except Exception:
            logger.warning("Failed to clear an undelivered registration OTP")
        raise _verification_unavailable() from exc
    except Exception:
        await db.rollback()
        try:
            redis_client.delete(otp_key)
        except Exception:
            logger.warning("Failed to clear a registration OTP after an error")
        logger.exception("Failed to create a verified registration session")
        raise _verification_unavailable()

    return RegisterResponse(
        user_id=new_user.id,
        full_name=new_user.full_name,
        email=new_user.email,
        needs_verification=True,
    )


async def login_user(payload: LoginRequest, db: AsyncSession, client_ip: str = "unknown"):
    if not payload.email or not payload.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required."
        )

    if not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required."
        )

    try:
        ensure_bcrypt_password_size(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    redis_client = get_redis()
    attempt_key = _login_attempt_key(str(payload.email), client_ip)
    if redis_client and int(redis_client.get(attempt_key) or 0) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    password_matches = verify_password(
        payload.password,
        user.hashed_password if user else DUMMY_PASSWORD_HASH,
    )
    if not user or not password_matches:
        _record_failed_login(redis_client, attempt_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    if not user.email_verified:
        return LoginResponse(
            needs_verification=True,
            email=user.email,
        ), None

    if redis_client:
        redis_client.delete(attempt_key)

    token = create_access_token(session_claims(user))
    refresh_token = create_refresh_token(session_claims(user))
    record_security_event(db, user.id, SecurityAction.password_login)
    await db.commit()

    return LoginResponse(
        needs_verification=False,
        access_token=token,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
    ), refresh_token


async def logout_user(current_user: User):
    return None


async def send_otp_email(email: str, otp: str):
    sender = _email_sender()
    try:
        await asyncio.to_thread(
            resend.Emails.send,
            {
                "from": sender,
                "to": [email],
                "subject": "Your Verification Code",
                "html": f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px;">
                    <h2>Email Verification</h2>
                    <p>Your verification code is:</p>

                    <div style="
                        font-size: 32px;
                        font-weight: bold;
                        letter-spacing: 8px;
                        background: #f5f5f5;
                        padding: 16px;
                        text-align: center;
                        border-radius: 8px;
                    ">
                        {otp}
                    </div>

                    <p>This code expires in <strong>5 minutes</strong>.</p>
                    <p>If you didn't request this code, you can safely ignore this email.</p>
                </div>
                """,
            }
        )
        logger.info("Verification email accepted for delivery")
    except Exception as exc:
        logger.exception("Verification email delivery failed")
        raise EmailDeliveryError("Verification email delivery failed.") from exc


def generate_six_digit_otp() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


async def request_otp_service(payload: OTPRequest, db: AsyncSession):
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification service is temporarily unavailable. Please try again later."
        )

    redis_key = f"otp:{payload.email}"
    attempts_key = f"otp_attempts:{payload.email}"
    cooldown_key = f"otp_cooldown:{payload.email}"

    try:
        if redis_client.get(cooldown_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Please wait before requesting another verification code.",
            )
        redis_client.set(cooldown_key, "1", ex=OTP_REQUEST_COOLDOWN_SECONDS)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Redis cooldown check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create verification session. Please try again.",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        return

    otp = generate_six_digit_otp()

    try:
        redis_client.set(redis_key, _otp_digest(otp), ex=OTP_EXPIRY_SECONDS)
        redis_client.delete(attempts_key)
    except Exception as e:
        logger.error(f"Redis set failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create verification session. Please try again."
        )

    try:
        await send_otp_email(payload.email, otp)
    except EmailDeliveryError as exc:
        try:
            redis_client.delete(redis_key)
            redis_client.delete(cooldown_key)
        except Exception:
            logger.warning("Failed to clear an undelivered verification code")
        raise _verification_unavailable() from exc


async def verify_otp_service(payload: OTPVerifyRequest, db: AsyncSession) -> bool:
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification service is temporarily unavailable. Please try again later."
        )

    redis_key = f"otp:{payload.email}"
    attempts_key = f"otp_attempts:{payload.email}"

    try:
        stored_otp = redis_client.get(redis_key)
    except Exception as e:
        logger.error(f"Redis get failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify code. Please try again."
        )

    if not stored_otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new one."
        )

    if not hmac.compare_digest(str(stored_otp), _otp_digest(payload.otp)):
        attempts = redis_client.incr(attempts_key)
        if attempts == 1:
            redis_client.expire(attempts_key, OTP_EXPIRY_SECONDS)
        if attempts >= OTP_MAX_ATTEMPTS:
            redis_client.delete(redis_key)
            redis_client.delete(attempts_key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many invalid attempts. Request a new verification code.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check and try again."
        )

    try:
        redis_client.delete(redis_key)
        redis_client.delete(attempts_key)
    except Exception as e:
        logger.warning(f"Failed to clear key {redis_key} post-verification: {e}")

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user:
        user.email_verified = True
        await db.commit()

    return True
