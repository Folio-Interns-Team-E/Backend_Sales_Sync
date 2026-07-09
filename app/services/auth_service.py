from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RegisterResponse
from app.core.security import (
    create_access_token,
    create_refresh_token,
    ensure_bcrypt_password_size,
    hash_password,
    verify_password,
)
import random
import logging
from fastapi import HTTPException, status, BackgroundTasks
from app.schemas.auth import OTPRequest, OTPVerifyRequest
from app.core.redis import get_redis

import resend

from app.config import settings

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)

#register user
async def register_user(payload: RegisterRequest, db: AsyncSession) -> RegisterResponse:
    try:
        ensure_bcrypt_password_size(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    
    #if email alr exists
    result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail = "Email already registered"
        )
    
    #creating a new user using the model
    new_user = User(
        full_name = payload.full_name,
        email = payload.email,
        hashed_password = hash_password(payload.password),
        #role=UserRole.admin  # first user is always admin
    )

    #changes in db
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)


    return RegisterResponse(
        user_id = new_user.id,
        full_name = new_user.full_name,
        email = new_user.email
    )

#login user
async def login_user(payload: LoginRequest, db: AsyncSession) -> TokenResponse:
    try:
        ensure_bcrypt_password_size(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    #get user by email
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    #if password wrong or user doesn't exist
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid credentials"
        )
    '''
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )
    '''
    
    #else
    token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token = token,
        user_id = user.id,
        full_name = user.full_name,
        email = user.email
    ), refresh_token

#logout user
async def logout_user(current_user: User):
    #client side
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

                    <p>This code expires in <strong>10 minutes</strong>.</p>
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

async def request_otp_service(payload: OTPRequest, background_tasks: BackgroundTasks):
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Caching service unconfigured or unavailable."
        )

    otp = generate_six_digit_otp()
    redis_key = f"otp:{payload.email}"
    
    try:
        # Using synchronous execution since your core setup uses the sync Upstash client
        redis_client.set(redis_key, otp, ex=300)
    except Exception as e:
        logger.error(f"Redis set failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate verification session."
        )
    
    # Safely hand off email execution to the background worker
    background_tasks.add_task(send_otp_email, payload.email, otp)


async def verify_otp_service(payload: OTPVerifyRequest) -> bool:
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Caching service unconfigured or unavailable."
        )

    redis_key = f"otp:{payload.email}"
    
    try:
        # Sync retrieval matching your core configuration
        stored_otp = redis_client.get(redis_key)
    except Exception as e:
        logger.error(f"Redis get failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete code verification link."
        )
    
    if not stored_otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired or was never requested."
        )
        
    if stored_otp != payload.otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code."
        )
        
    # Prevent replay attacks by clearing out the verified key instantly
    try:
        redis_client.delete(redis_key)
    except Exception as e:
        logger.warning(f"Failed to clear key {redis_key} post-verification: {e}")
        
    return True