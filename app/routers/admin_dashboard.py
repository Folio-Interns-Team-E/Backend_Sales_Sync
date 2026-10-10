from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_current_user, require_role
from app.models.team_member import MemberRole
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.admin_dashboard_service import AdminDashboardService
from app.services.audit_service import record_audit_event
from app.services.data_export_service import export_workspace_data


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=ApiResponse[dict])
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(require_role(MemberRole.admin)),
):
    data = await AdminDashboardService(db).overview(team_ctx.team_id)
    return ApiResponse(success=True, message="Admin overview fetched", data=data)


@router.get("/exports/{resource}.csv")
async def export_workspace_csv(
    resource: Literal["leads", "contacts", "opportunities", "audit"],
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(require_role(MemberRole.admin)),
    user: User = Depends(get_current_user),
):
    content, row_count = await export_workspace_data(db, team_ctx.team_id, resource)
    record_audit_event(db, team_ctx.team_id, user.id, "workspace.data_exported", "export", resource)
    await db.commit()
    filename = f"salesync-{resource}-{date.today().isoformat()}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Export-Row-Count": str(row_count),
        },
    )
