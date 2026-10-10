from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import TeamContext, require_role
from app.models.team_member import MemberRole
from app.schemas.audit import AuditPage
from app.schemas.common import ApiResponse
from app.services.audit_service import list_audit_events

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=ApiResponse[AuditPage])
async def audit_events(response: Response, limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None, max_length=256), db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(require_role(MemberRole.admin, MemberRole.manager))):
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(success=True, message="Audit events fetched", data=await list_audit_events(db, team_ctx.team_id, limit, cursor))
