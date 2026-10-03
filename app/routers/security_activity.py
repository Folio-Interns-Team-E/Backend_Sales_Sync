from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.security_activity import SecurityActivityPage
from app.services.security_activity import list_security_activity

router = APIRouter(prefix="/auth", tags=["account security"])


@router.get("/activity", response_model=ApiResponse[SecurityActivityPage])
async def security_activity(
    response: Response,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=256),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(success=True, message="Security activity", data=await list_security_activity(db, current_user.id, limit, cursor))
