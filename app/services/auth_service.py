from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RegisterResponse, LoginResponse
from app.core.security import (
    create_access_token,
    create_refresh_token,
    ensure_bcrypt_password_size,
    hash_password,
    verify_password,
)
import random
import logging
from datetime import datetime, timedelta, timezone
from fastapi import BackgroundTasks
from app.schemas.auth import OTPRequest, OTPVerifyRequest
from app.core.redis import get_redis

import resend

from app.config import settings

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)

OTP_EXPIRY_SECONDS = 300


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

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # Send OTP via Redis + Resend
    redis_client = get_redis()
    if redis_client:
        otp = generate_six_digit_otp()
        try:
            redis_client.set(f"otp:{new_user.email}", otp, ex=OTP_EXPIRY_SECONDS)
            await send_otp_email(new_user.email, otp)
        except Exception:
            logger.exception("Failed to send OTP after registration for %s", new_user.email)

    return RegisterResponse(
        user_id=new_user.id,
        full_name=new_user.full_name,
        email=new_user.email,
        needs_verification=True,
    )


async def login_user(payload: LoginRequest, db: AsyncSession):
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

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account found with this email. Please register first."
        )

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password. Please try again."
        )

    if not user.email_verified:
        return LoginResponse(
            needs_verification=True,
            email=user.email,
        ), None

    token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

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
    try:
        resend.Emails.send(
            {
                "from": settings.FROM_EMAIL,
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
        logger.info("OTP email sent to %s", email)
    except Exception:
        logger.exception("Failed to send OTP email to %s", email)
        raise


def generate_six_digit_otp() -> str:
    return f"{random.randint(100000, 999999)}"


async def request_otp_service(payload: OTPRequest, background_tasks: BackgroundTasks, db: AsyncSession):
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification service is temporarily unavailable. Please try again later."
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No account found with this email."
        )

    otp = generate_six_digit_otp()
    redis_key = f"otp:{payload.email}"

    try:
        redis_client.set(redis_key, otp, ex=OTP_EXPIRY_SECONDS)
    except Exception as e:
        logger.error(f"Redis set failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create verification session. Please try again."
        )

    background_tasks.add_task(send_otp_email, payload.email, otp)


async def verify_otp_service(payload: OTPVerifyRequest, db: AsyncSession) -> bool:
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification service is temporarily unavailable. Please try again later."
        )

    redis_key = f"otp:{payload.email}"

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

    if stored_otp != payload.otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check and try again."
        )

    try:
        redis_client.delete(redis_key)
    except Exception as e:
        logger.warning(f"Failed to clear key {redis_key} post-verification: {e}")

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user:
        user.email_verified = True
        await db.commit()

    return True
