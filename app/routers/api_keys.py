import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_current_user, require_role
from app.models.api_key import WorkspaceApiKey
from app.models.team_member import MemberRole
from app.models.user import User
from app.schemas.api_keys import ApiKeyCreate, ApiKeyResponse
from app.schemas.common import ApiResponse
from app.services.audit_service import record_audit_event

router = APIRouter(prefix="/admin/api-keys", tags=["api-keys"])


def require_session_user(user: User) -> None:
    if getattr(user, "_api_key_team_id", None):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys cannot manage workspace credentials")


@router.get("/", response_model=ApiResponse[list[ApiKeyResponse]])
async def list_api_keys(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(require_role(MemberRole.admin)), user: User = Depends(get_current_user)):
    require_session_user(user)
    rows = (await db.execute(select(WorkspaceApiKey).where(WorkspaceApiKey.team_id == team_ctx.team_id).order_by(WorkspaceApiKey.created_at.desc()))).scalars().all()
    return ApiResponse(success=True, message="API keys fetched", data=rows)


@router.post("/", response_model=ApiResponse[dict], status_code=201)
async def create_api_key(payload: ApiKeyCreate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(require_role(MemberRole.admin)), user: User = Depends(get_current_user)):
    require_session_user(user)
    secret = "ss_live_" + secrets.token_urlsafe(32)
    row = WorkspaceApiKey(team_id=team_ctx.team_id, created_by=user.id, name=payload.name.strip(), key_prefix=secret[:16], key_hash=hashlib.sha256(secret.encode()).hexdigest(), expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days))
    db.add(row); await db.flush()
    record_audit_event(db, team_ctx.team_id, user.id, "workspace.api_key_created", "api_key", row.id)
    await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="API key created. Store it now; it will not be shown again.", data={"key": secret, "api_key": ApiKeyResponse.model_validate(row).model_dump(mode="json")})


@router.delete("/{key_id}", response_model=ApiResponse[dict])
async def revoke_api_key(key_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(require_role(MemberRole.admin)), user: User = Depends(get_current_user)):
    require_session_user(user)
    row = await db.scalar(select(WorkspaceApiKey).where(WorkspaceApiKey.id == key_id, WorkspaceApiKey.team_id == team_ctx.team_id))
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    if not row.revoked_at:
        row.revoked_at = datetime.now(timezone.utc)
        record_audit_event(db, team_ctx.team_id, user.id, "workspace.api_key_revoked", "api_key", row.id)
        await db.commit()
    return ApiResponse(success=True, message="API key revoked", data={})
