from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from dataclasses import dataclass
from app.database import get_db
from app.models.user import User
from app.models.team_member import TeamMember, MemberRole
from app.core.security import decode_access_token, token_is_revoked, session_matches_user
from typing import Optional
from datetime import datetime, timezone
import hashlib
from app.models.api_key import WorkspaceApiKey

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class TeamContext:
    team_id: UUID
    role: MemberRole


async def get_current_user(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
        x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
        db: AsyncSession = Depends(get_db)
) -> User:
    if not credentials and x_api_key:
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        api_key = await db.scalar(select(WorkspaceApiKey).where(
            WorkspaceApiKey.key_hash == key_hash,
            WorkspaceApiKey.revoked_at.is_(None),
            WorkspaceApiKey.expires_at > datetime.now(timezone.utc),
        ))
        if not api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired API key", headers={"WWW-Authenticate": "ApiKey"})
        user = await db.scalar(select(User).where(User.id == api_key.created_by))
        if not user or not user.email_verified:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner is unavailable")
        api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        setattr(user, "_api_key_team_id", api_key.team_id)
        return user

    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})

    token = credentials.credentials

    payload = decode_access_token(token)

    if payload is None or token_is_revoked(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        user_uuid = UUID(str(user_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if user is None or not user.email_verified or not session_matches_user(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return user


async def get_team_context(
        x_team_id: Optional[str] = Header(None, alias="X-Team-Id"),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
) -> TeamContext:
    api_key_team_id = getattr(current_user, "_api_key_team_id", None)
    if not x_team_id and api_key_team_id:
        x_team_id = str(api_key_team_id)
    if not x_team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Team-Id header is required"
        )
    try:
        team_uuid = UUID(x_team_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid team ID format"
        )
    if api_key_team_id and team_uuid != api_key_team_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is not valid for this workspace")

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.user_id == current_user.id,
            TeamMember.team_id == team_uuid,
        )
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this team"
        )

    return TeamContext(team_id=team_uuid, role=membership.role)


def require_role(*roles: MemberRole):
    async def role_checker(
        team_ctx: TeamContext = Depends(get_team_context),
    ):
        if team_ctx.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return team_ctx
    return role_checker
