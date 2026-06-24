from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User, UserRole
from app.models.team import Team
from app.core.security import decode_access_token

#pulls token string from the authorization header
bearer_scheme = HTTPBearer()

#get current user
async def get_current_user(
        credentials: HTTPAuthorizationCredentials=Depends(bearer_scheme),
        db: AsyncSession = Depends(get_db)
) -> User:
    
    token = credentials.credentials

    #decode & validate jwt
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid or expired token",
            headers = {"WWW-Authenticate": "Bearer"} #auth scheme to use
        )
    
    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid token payload",
            headers = {"WWW-Authenticate": "Bearer"}
        )
    
    #fetch user from db
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return user


#role based access control for teams
def require_role(*roles: UserRole):
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code = status.HTTP_403_FORBIDDEN,
                detail = "Insufficient permissions"
            )
        return current_user
    return role_checker