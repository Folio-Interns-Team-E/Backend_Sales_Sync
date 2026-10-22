from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_current_user, get_team_context
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.opportunities import OpportunityCreate, OpportunityResponse, OpportunitySummary, OpportunityUpdate
from app.services.opportunities_service import OpportunityService, serialize_opportunity
from app.services.financial_dashboard_service import FinancialDashboardService

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("/financial-dashboard", response_model=ApiResponse[dict])
async def financial_dashboard(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
    current_user: User = Depends(get_current_user),
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date cannot be after to_date")
    data = await FinancialDashboardService(db).dashboard(
        team_ctx.team_id, current_user.id, team_ctx.role, from_date, to_date
    )
    return ApiResponse(success=True, message="Financial dashboard fetched", data=data)


@router.get("/summary", response_model=ApiResponse[OpportunitySummary])
async def opportunity_summary(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), current_user: User = Depends(get_current_user)):
    data = await OpportunityService(db).summary(team_ctx.team_id, current_user.id, team_ctx.role)
    return ApiResponse(success=True, message="Opportunity summary fetched", data=data)


@router.get("/", response_model=ApiResponse[list[OpportunityResponse]])
async def list_opportunities(stage: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), current_user: User = Depends(get_current_user)):
    records = await OpportunityService(db).list(team_ctx.team_id, current_user.id, team_ctx.role, stage)
    return ApiResponse(success=True, message="Opportunities fetched", data=[serialize_opportunity(item) for item in records])


@router.post("/", response_model=ApiResponse[OpportunityResponse], status_code=status.HTTP_201_CREATED)
async def create_opportunity(payload: OpportunityCreate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), current_user: User = Depends(get_current_user)):
    record = await OpportunityService(db).create(team_ctx.team_id, current_user.id, team_ctx.role, payload)
    return ApiResponse(success=True, message="Opportunity created", data=serialize_opportunity(record))


@router.get("/{opportunity_id}", response_model=ApiResponse[OpportunityResponse])
async def get_opportunity(opportunity_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), current_user: User = Depends(get_current_user)):
    record = await OpportunityService(db).get(opportunity_id, team_ctx.team_id, current_user.id, team_ctx.role)
    return ApiResponse(success=True, message="Opportunity fetched", data=serialize_opportunity(record))


@router.patch("/{opportunity_id}", response_model=ApiResponse[OpportunityResponse])
async def update_opportunity(opportunity_id: UUID, payload: OpportunityUpdate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), current_user: User = Depends(get_current_user)):
    record = await OpportunityService(db).update(opportunity_id, team_ctx.team_id, current_user.id, team_ctx.role, payload)
    return ApiResponse(success=True, message="Opportunity updated", data=serialize_opportunity(record))


@router.delete("/{opportunity_id}", response_model=ApiResponse[dict])
async def delete_opportunity(opportunity_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), current_user: User = Depends(get_current_user)):
    await OpportunityService(db).delete(opportunity_id, team_ctx.team_id, current_user.id, team_ctx.role)
    return ApiResponse(success=True, message="Opportunity deleted", data={})
