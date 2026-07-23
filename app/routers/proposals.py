from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_team_context, TeamContext, get_current_user
from app.models.user import User
from app.schemas.proposals import (
    ProposalCreate, ProposalUpdate, ProposalOutcomeUpdate, ProposalStatusUpdate, ProposalResponse,
    ProposalTemplateUpdate, ProposalTemplateResponse,
)
from app.schemas.common import ApiResponse
from app.services.proposals_service import ProposalService
from typing import Optional
router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("/", response_model=ApiResponse[list[ProposalResponse]])
async def list_proposals(
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    proposals = await service.list_proposals(team_ctx.team_id)
    return ApiResponse(success=True, message="Proposals fetched successfully", data=proposals)





@router.post("/", response_model=ApiResponse[ProposalResponse], status_code=201)
async def create_proposal(
    payload: ProposalCreate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    proposal = await service.create_proposal(
        team_ctx.team_id, payload.file_url, payload.lead_id,
        payload.file_type, payload.file_size,
        payload.template_id, payload.ai_metadata,
    )
    return ApiResponse(success=True, message="Proposal created successfully", data=proposal)




@router.get("/template", response_model=ApiResponse[Optional[ProposalTemplateResponse]])
async def get_template(
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    template = await service.get_template(team_ctx.team_id)
    return ApiResponse(success=True, message="Template fetched", data=template)


@router.put("/template", response_model=ApiResponse[ProposalTemplateResponse])
async def upsert_template(
    payload: ProposalTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    template = await service.upsert_template(
        team_ctx.team_id, payload.template_name,
        payload.file_url, payload.file_type, payload.file_size,
    )
    return ApiResponse(success=True, message="Template saved", data=template)


@router.post("/template/upload", response_model=ApiResponse[ProposalTemplateResponse], status_code=201)
async def upload_template(
    file: UploadFile = File(...),
    template_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
    current_user: User = Depends(get_current_user),
):
    file_bytes = await file.read()
    service = ProposalService(db)

    allowed_types = {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    allowed_exts = {".doc", ".docx"}
    fname_lower = (file.filename or "").lower()
    ext = fname_lower.rsplit(".", 1)[-1] if "." in fname_lower else ""
    if file.content_type not in allowed_types and f".{ext}" not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .doc and .docx files are accepted",
        )

    template = await service.upload_template(
        team_ctx.team_id,
        current_user.id,
        template_name=template_name,
        file_bytes=file_bytes,
        filename=file.filename or "template",
        content_type=file.content_type or "application/octet-stream",
    )
    return ApiResponse(success=True, message="Template uploaded successfully", data=template)


@router.delete("/template", response_model=ApiResponse[dict])
async def delete_template(
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    await service.delete_template(team_ctx.team_id)
    return ApiResponse(success=True, message="Template deleted", data={})

@router.patch("/{proposal_id}", response_model=ApiResponse[ProposalResponse])
async def update_proposal(
    proposal_id: UUID,
    payload: ProposalUpdate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    proposal = await service.update_proposal(
        proposal_id, team_ctx.team_id, payload.file_url,
        payload.file_type, payload.file_size, payload.lead_id,
        payload.template_id, payload.ai_metadata,
    )
    return ApiResponse(success=True, message="Proposal updated successfully", data=proposal)



@router.delete("/{proposal_id}", response_model=ApiResponse[dict])
async def delete_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    await service.delete_proposal(proposal_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Proposal deleted", data={})

@router.patch("/{proposal_id}/status", response_model=ApiResponse[ProposalResponse])
async def update_proposal_status(
    proposal_id: UUID,
    payload: ProposalStatusUpdate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    proposal = await service.update_status(proposal_id, team_ctx.team_id, payload.status)
    return ApiResponse(success=True, message="Status updated", data=proposal)


@router.patch("/{proposal_id}/outcome", response_model=ApiResponse[ProposalResponse])
async def update_proposal_outcome(
    proposal_id: UUID,
    payload: ProposalOutcomeUpdate,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    proposal = await service.update_outcome(proposal_id, team_ctx.team_id, payload.outcome)
    return ApiResponse(success=True, message="Outcome updated", data=proposal)


@router.get("/{proposal_id}", response_model=ApiResponse[ProposalResponse])
async def get_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
):
    service = ProposalService(db)
    proposal = await service.get_proposal(proposal_id, team_ctx.team_id)
    return ApiResponse(success=True, message="Proposal fetched successfully", data=proposal)