from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_current_user, get_team_context
from app.models.notification import Notification
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.notifications import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/", response_model=ApiResponse[list[NotificationResponse]])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
    user: User = Depends(get_current_user),
):
    statement = select(Notification).where(Notification.team_id == team_ctx.team_id, Notification.user_id == user.id)
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    rows = (await db.execute(statement.order_by(Notification.created_at.desc()).limit(limit))).scalars().all()
    return ApiResponse(success=True, message="Notifications fetched", data=rows)


@router.post("/read-all", response_model=ApiResponse[dict])
async def read_all_notifications(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    result = await db.execute(update(Notification).where(Notification.team_id == team_ctx.team_id, Notification.user_id == user.id, Notification.is_read.is_(False)).values(is_read=True))
    await db.commit()
    return ApiResponse(success=True, message="Notifications marked as read", data={"updated": result.rowcount or 0})


@router.post("/{notification_id}/read", response_model=ApiResponse[dict])
async def read_notification(notification_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await db.scalar(select(Notification).where(Notification.id == notification_id, Notification.team_id == team_ctx.team_id, Notification.user_id == user.id))
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    row.is_read = True
    await db.commit()
    return ApiResponse(success=True, message="Notification marked as read", data={})
