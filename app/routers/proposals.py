from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.proposals import (
    ProposalCreate, ProposalUpdate, ProposalOutcomeUpdate, ProposalStatusUpdate, ProposalResponse,
    ProposalTemplateUpdate, ProposalTemplateResponse,
)
from app.schemas.common import ApiResponse
from app.services.proposals_service import ProposalService

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("/", response_model=ApiResponse[list[ProposalResponse]])
async def list_proposals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    proposals = await service.list_proposals(current_user.id)
    return ApiResponse(success=True, message="Proposals fetched successfully", data=proposals)


@router.get("/{proposal_id}", response_model=ApiResponse[ProposalResponse])
async def get_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    proposal = await service.get_proposal(proposal_id, current_user.id)
    return ApiResponse(success=True, message="Proposal fetched successfully", data=proposal)


@router.post("/", response_model=ApiResponse[ProposalResponse], status_code=201)
async def create_proposal(
    payload: ProposalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    proposal = await service.create_proposal(
        current_user.id, payload.file_url, payload.lead_id,
        payload.file_type, payload.file_size,
        payload.template_id, payload.ai_metadata,
    )
    return ApiResponse(success=True, message="Proposal created successfully", data=proposal)


@router.patch("/{proposal_id}", response_model=ApiResponse[ProposalResponse])
async def update_proposal(
    proposal_id: UUID,
    payload: ProposalUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    proposal = await service.update_proposal(
        proposal_id, current_user.id, payload.file_url,
        payload.file_type, payload.file_size, payload.lead_id,
        payload.template_id, payload.ai_metadata,
    )
    return ApiResponse(success=True, message="Proposal updated successfully", data=proposal)


@router.get("/template", response_model=ApiResponse[ProposalTemplateResponse])
async def get_template(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    template = await service.get_template(current_user.id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No template found")
    return ApiResponse(success=True, message="Template fetched", data=template)


@router.put("/template", response_model=ApiResponse[ProposalTemplateResponse])
async def upsert_template(
    payload: ProposalTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    template = await service.upsert_template(
        current_user.id, payload.template_name,
        payload.file_url, payload.file_type, payload.file_size,
    )
    return ApiResponse(success=True, message="Template saved", data=template)


@router.delete("/{proposal_id}", response_model=ApiResponse[dict])
async def delete_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    await service.delete_proposal(proposal_id, current_user.id)
    return ApiResponse(success=True, message="Proposal deleted", data={})

@router.patch("/{proposal_id}/status", response_model=ApiResponse[ProposalResponse])
async def update_proposal_status(
    proposal_id: UUID,
    payload: ProposalStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    proposal = await service.update_status(proposal_id, current_user.id, payload.status)
    return ApiResponse(success=True, message="Status updated", data=proposal)


@router.patch("/{proposal_id}/outcome", response_model=ApiResponse[ProposalResponse])
async def update_proposal_outcome(
    proposal_id: UUID,
    payload: ProposalOutcomeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProposalService(db)
    proposal = await service.update_outcome(proposal_id, current_user.id, payload.outcome)
    return ApiResponse(success=True, message="Outcome updated", data=proposal)