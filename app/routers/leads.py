from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_team_context, TeamContext
from app.models.user import User
from app.schemas.leads import LeadCreate, LeadUpdate, LeadPatch, LeadResponse, LeadListResponse, LeadGenerateRequest, LeadGenerateResponse, LeadImportResponse, LeadProviderUpdate, LeadProviderStatus
from app.schemas.common import ApiResponse
from app.services.leads_service import LeadService
from app.services.lead_generation_service import LeadGenerationService
from app.services.lead_import_service import LeadImportService
from app.services.lead_provider_service import get_provider, reset_usage_if_needed, save_provider
from app.models.team_member import MemberRole

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("/provider", response_model=ApiResponse[LeadProviderStatus])
async def provider_status(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    record = await get_provider(db, team_ctx.team_id)
    if record:
        reset_usage_if_needed(record)
        await db.commit()
    data = LeadProviderStatus(provider="apollo", connected=bool(record), monthly_limit=record.monthly_limit if record else 100, used_this_month=record.used_this_month if record else 0)
    return ApiResponse(success=True, message="Lead provider status", data=data)


@router.put("/provider", response_model=ApiResponse[LeadProviderStatus])
async def configure_provider(payload: LeadProviderUpdate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    if team_ctx.role not in {MemberRole.admin, MemberRole.manager}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can configure lead providers")
    record = await save_provider(db, team_ctx.team_id, payload.api_key, payload.monthly_limit)
    return ApiResponse(success=True, message="Apollo credentials saved securely", data=LeadProviderStatus(provider="apollo", connected=True, monthly_limit=record.monthly_limit, used_this_month=record.used_this_month))


@router.delete("/provider", response_model=ApiResponse[dict])
async def disconnect_provider(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    if team_ctx.role not in {MemberRole.admin, MemberRole.manager}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can configure lead providers")
    record = await get_provider(db, team_ctx.team_id)
    if record:
        await db.delete(record)
        await db.commit()
    return ApiResponse(success=True, message="Apollo disconnected", data={})


@router.post("/generate", response_model=ApiResponse[LeadGenerateResponse])
async def generate_leads(
    payload: LeadGenerateRequest,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    leads, skipped = await LeadGenerationService(db).generate(team_ctx.team_id, payload.limit)
    data = LeadGenerateResponse(
        created=len(leads),
        skipped_duplicates=skipped,
        leads=[LeadListResponse.model_validate(lead) for lead in leads],
    )
    return ApiResponse(success=True, message=f"Generated {len(leads)} Apollo leads", data=data)


@router.post("/import", response_model=ApiResponse[LeadImportResponse])
async def import_leads(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload a CSV file")
    leads, duplicates, invalid = await LeadImportService(db).import_csv(team_ctx.team_id, await file.read())
    data = LeadImportResponse(
        created=len(leads),
        skipped_duplicates=duplicates,
        invalid_rows=invalid,
        leads=[LeadListResponse.model_validate(lead) for lead in leads],
    )
    return ApiResponse(success=True, message=f"Imported {len(leads)} leads", data=data)


@router.get("/", response_model=ApiResponse[list[LeadListResponse]])
async def list_leads(
    status: str = Query(None),
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    leads = await service.list_leads(team_ctx.team_id, status)
    return ApiResponse(success=True, message="Leads fetched successfully", data=leads)


@router.get("/{lead_id}", response_model=ApiResponse[LeadResponse])
async def get_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    lead = await service.get_lead(lead_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Lead fetched successfully", data=lead)


@router.post("/", response_model=ApiResponse[LeadResponse], status_code=201)
async def create_lead(
    payload: LeadCreate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    lead = await service.create_lead(
        team_ctx.team_id, payload.name, payload.company,
        payload.title, payload.email, payload.source
    )
    return ApiResponse(success=True, message="Lead created successfully", data=lead)


@router.patch("/{lead_id}", response_model=ApiResponse[LeadResponse])
async def update_lead(
    lead_id: UUID,
    payload: LeadPatch,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    lead = await service.update_lead(
        lead_id, team_ctx.team_id,
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
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    lead = await service.update_lead_status(lead_id, team_ctx.team_id, payload.status)
    return ApiResponse(success=True, message="Lead status updated", data=lead)


@router.post("/{lead_id}/qualify", response_model=ApiResponse[LeadResponse])
async def qualify_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    lead = await service.qualify_lead(lead_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Lead qualified", data=lead)


@router.post("/{lead_id}/discard", response_model=ApiResponse[LeadResponse])
async def discard_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    lead = await service.discard_lead(lead_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Lead discarded", data=lead)


@router.delete("/{lead_id}", response_model=ApiResponse[dict])
async def delete_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = LeadService(db)
    await service.delete_lead(lead_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Lead deleted", data={})
