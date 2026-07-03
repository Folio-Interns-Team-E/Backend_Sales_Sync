from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.core.security import (
    create_access_token,
    ensure_bcrypt_password_size,
    hash_password,
    verify_password,
)

#register user
async def register_user(payload: RegisterRequest, db: AsyncSession) -> TokenResponse:
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

    #generate token
    token = create_access_token({"sub": str(new_user.id)})

    return TokenResponse(
        access_token = token,
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
    
    #else
    token = create_access_token({"sub": str(user.id)})

    return TokenResponse(
        access_token = token,
        user_id = user.id,
        full_name = user.full_name,
        email = user.email
    )

#logout user
async def logout_user(current_user: User):
    #client side
    return None
