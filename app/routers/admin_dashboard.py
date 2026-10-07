from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_team_context, require_role
from app.models.team_member import MemberRole
from app.schemas.common import ApiResponse
from app.services.admin_dashboard_service import AdminDashboardService


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=ApiResponse[dict])
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(require_role(MemberRole.admin)),
):
    data = await AdminDashboardService(db).overview(team_ctx.team_id)
    return ApiResponse(success=True, message="Admin overview fetched", data=data)
