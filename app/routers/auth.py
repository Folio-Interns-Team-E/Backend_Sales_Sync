from fastapi import APIRouter, Depends, status, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import BackgroundTasks
from app.schemas.auth import OTPRequest, OTPVerifyRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import request_otp_service, verify_otp_service
from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RegisterResponse, LoginResponse
from app.schemas.common import ApiResponse
from app.services.auth_service import register_user, login_user, logout_user
from app.middleware.auth_middleware import get_current_user
from app.core.redis import get_redis
from app.core.security import decode_token_without_verification
import time

#router init (auth grouping)
router = APIRouter(prefix="/auth", tags=["auth"])

#register user endpoint
@router.post("/register", response_model=ApiResponse[RegisterResponse], status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    token = await register_user(payload, db)
    return ApiResponse(success=True, message="Account created successfully. Please verify your email.", data=token)

#login endpoint
@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    result, refresh_token = await login_user(payload, db)

    if result.needs_verification:
        return ApiResponse(
            success=True,
            message="Email not verified",
            data=result
        )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,       
        samesite="lax",
        max_age=7 * 24 * 60 * 60, 
    )

    return ApiResponse(
        success=True,
        message="Login successful",
        data=result
    )

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, refresh_token: str | None = Cookie(default=None)):
    # Clear client cookie
    response.delete_cookie(
        key="refresh_token",
        path="/auth/refresh",
        httponly=True,
        samesite="lax",
        secure=True
    )

    if refresh_token:
        redis = get_redis()
        payload = decode_token_without_verification(refresh_token)
        
        if redis and payload and "exp" in payload:
            ttl_seconds = int(payload["exp"] - time.time())
            if ttl_seconds > 0:
                redis.setex(f"blocklist:{refresh_token}", ttl_seconds, "revoked")
                
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/otp/request", response_model=ApiResponse[dict])
async def request_otp(payload: OTPRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    await request_otp_service(payload, background_tasks, db)
    return ApiResponse(
        success=True, 
        message="Verification code sent to your email.", 
        data={}
    )

@router.post("/otp/verify", response_model=ApiResponse[dict])
async def verify_otp(payload: OTPVerifyRequest, db: AsyncSession = Depends(get_db)):
    await verify_otp_service(payload, db)
    return ApiResponse(
        success=True, 
        message="Email verified successfully.", 
        data={}
    )