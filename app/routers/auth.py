from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession


#dependencies
from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RegisterResponse
from app.schemas.common import ApiResponse
from app.services.auth_service import register_user, login_user, logout_user
from app.middleware.auth_middleware import get_current_user

#router init (auth grouping)
router = APIRouter(prefix="/auth", tags=["auth"])

#register user endpoint
@router.post("/register", response_model=ApiResponse[RegisterResponse], status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    token = await register_user(payload, db)
    return ApiResponse(success=True, message="Account created successfully", data=token)

#login endpoint
@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    result, refresh_token = await login_user(payload, db)


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

#logout endpoint
@router.post("/logout", response_model=ApiResponse[dict])
async def logout(current_user = Depends(get_current_user)):
    await logout_user(current_user)
    return ApiResponse(success=True, message="Logged out successfully", data={})
