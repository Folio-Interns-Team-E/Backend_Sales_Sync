from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.auth import OTPRequest, OTPVerifyRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import request_otp_service, verify_otp_service
from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, RegisterResponse, LoginResponse
from app.services.auth_service import register_user, login_user
from app.models.user import User
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    revoke_token,
    token_is_revoked,
    session_claims,
    session_matches_user,
)
from app.config import settings
from uuid import UUID
from app.schemas.auth import PasswordResetRequest, PasswordResetConfirm
from app.services.password_recovery import request_reset, confirm_reset
from app.middleware.csrf import require_auth_request

#router init (auth grouping)
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_auth_request)])


@router.post("/password/request", response_model=ApiResponse[dict])
async def request_password_reset(payload: PasswordResetRequest, request: Request,
                                 background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    await request_reset(str(payload.email), request.client.host if request.client else "unknown", background_tasks, db)
    return ApiResponse(success=True, message="If an account exists, a recovery code will be sent to your email.", data={})


@router.post("/password/reset", response_model=ApiResponse[dict])
async def reset_password(payload: PasswordResetConfirm, response: Response, db: AsyncSession = Depends(get_db)):
    await confirm_reset(payload.token, payload.password, db)
    _clear_refresh_cookie(response)
    return ApiResponse(success=True, message="Password updated. Please log in again.", data={})


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    # Remove the old cookie so direct API requests cannot send duplicate values.
    response.delete_cookie("refresh_token", path="/auth")
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.app_env.lower() != "development",
        samesite=settings.refresh_cookie_samesite,
        path="/",
        max_age=7 * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie("refresh_token", path="/auth")
    response.delete_cookie(
        key="refresh_token",
        path="/",
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
        secure=settings.app_env.lower() != "development",
    )

#register user endpoint
@router.post("/register", response_model=ApiResponse[RegisterResponse], status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    token = await register_user(payload, db)
    return ApiResponse(success=True, message="Account created successfully. Please verify your email.", data=token)

#login endpoint
@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    result, refresh_token = await login_user(payload, db, client_ip=client_ip)

    if result.needs_verification:
        return ApiResponse(
            success=True,
            message="Email not verified",
            data=result
        )

    _set_refresh_cookie(response, refresh_token)

    return ApiResponse(
        success=True,
        message="Login successful",
        data=result
    )

@router.post("/refresh", response_model=ApiResponse[LoginResponse])
async def refresh_session(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    payload = decode_refresh_token(refresh_token) if refresh_token else None
    if payload is None or token_is_revoked(payload) or not revoke_token(payload):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    try:
        user_id = UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.email_verified or not session_matches_user(payload, user):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    access_token = create_access_token(session_claims(user))
    rotated_refresh_token = create_refresh_token(session_claims(user))
    _set_refresh_cookie(response, rotated_refresh_token)

    return ApiResponse(
        success=True,
        message="Session refreshed",
        data=LoginResponse(
            access_token=access_token,
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
        ),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload:
            revoke_token(payload)

    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_access_token(authorization[7:].strip())
        if payload:
            revoke_token(payload)

    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


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
