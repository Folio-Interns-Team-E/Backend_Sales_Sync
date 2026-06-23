from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

#dependencies
from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.services.auth_service import register_user, login_user, logout_user
from app.middleware.auth_middleware import get_current_user

#router init (auth grouping)
router = APIRouter(prefix="/auth", tags=["auth"])

#register user endpoint
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    return await register_user(payload_db)

#login endpoint
@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    return await login_user(payload, db)

#logout endpoint
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user = Depends(get_current_user)):
    return await logout_user(current_user)