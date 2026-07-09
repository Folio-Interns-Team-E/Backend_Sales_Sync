from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.leads import LeadCreate, LeadUpdate, LeadPatch, LeadResponse, LeadListResponse
from app.schemas.common import ApiResponse
from app.services.leads_service import LeadService

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("/", response_model=ApiResponse[list[LeadListResponse]])
async def list_leads(
    status: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    leads = await service.list_leads(current_user.id, status)
    return ApiResponse(success=True, message="Leads fetched successfully", data=leads)


@router.get("/{lead_id}", response_model=ApiResponse[LeadResponse])
async def get_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    lead = await service.get_lead(lead_id, current_user.id)
    return ApiResponse(success=True, message="Lead fetched successfully", data=lead)


@router.post("/", response_model=ApiResponse[LeadResponse], status_code=201)
async def create_lead(
    payload: LeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    lead = await service.create_lead(
        current_user.id, payload.name, payload.company,
        payload.title, payload.email, payload.source
    )
    return ApiResponse(success=True, message="Lead created successfully", data=lead)


@router.patch("/{lead_id}", response_model=ApiResponse[LeadResponse])
async def update_lead(
    lead_id: UUID,
    payload: LeadPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    lead = await service.update_lead(
        lead_id, current_user.id,
        name=payload.name, company=payload.company,
        title=payload.title, email=payload.email,
        source=payload.source,
    )
    return ApiResponse(success=True, message="Lead updated successfully", data=lead)


@router.patch("/{lead_id}/status", response_model=ApiResponse[LeadResponse])
async def update_lead_status(
    lead_id: UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    lead = await service.update_lead_status(lead_id, current_user.id, payload.status)
    return ApiResponse(success=True, message="Lead status updated", data=lead)


@router.post("/{lead_id}/qualify", response_model=ApiResponse[LeadResponse])
async def qualify_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    lead = await service.qualify_lead(lead_id, current_user.id)
    return ApiResponse(success=True, message="Lead qualified", data=lead)


@router.post("/{lead_id}/discard", response_model=ApiResponse[LeadResponse])
async def discard_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    lead = await service.discard_lead(lead_id, current_user.id)
    return ApiResponse(success=True, message="Lead discarded", data=lead)


@router.delete("/{lead_id}", response_model=ApiResponse[dict])
async def delete_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LeadService(db)
    await service.delete_lead(lead_id, current_user.id)
    return ApiResponse(success=True, message="Lead deleted", data={})
