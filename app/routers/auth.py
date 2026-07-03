from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

#dependencies
from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.schemas.common import ApiResponse
from app.services.auth_service import register_user, login_user, logout_user
from app.middleware.auth_middleware import get_current_user

#router init (auth grouping)
router = APIRouter(prefix="/auth", tags=["auth"])

#register user endpoint
@router.post("/register", response_model=ApiResponse[TokenResponse], status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    token = await register_user(payload, db)
    return ApiResponse(success=True, message="Account created successfully", data=token)

#login endpoint
@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    token = await login_user(payload, db)
    return ApiResponse(success=True, message="Logged in successfully", data=token)

#logout endpoint
@router.post("/logout", response_model=ApiResponse[dict])
async def logout(current_user = Depends(get_current_user)):
    await logout_user(current_user)
    return ApiResponse(success=True, message="Logged out successfully", data={})
