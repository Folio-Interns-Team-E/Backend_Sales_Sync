from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID
import logging

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.leads import (
    GenerateLeadsRequest,
    GenerateLeadsResponse,
    LeadDetailResponse,
    LeadListResponse,
    LeadResponse,
    LeadStatusUpdate,
    ManualLeadCreate,
    OutreachDraftSave,
    OutreachEmailResponse,
    BantBreakdown,
    MeddicBreakdown,
)
from app.services.leads_service import LeadsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["leads"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_response(lead) -> LeadResponse:
    return LeadResponse(
        id=lead.id,
        initials=lead.initials or "?",
        name=lead.name,
        company=lead.company,
        title=lead.title or "",
        email=lead.email or "",
        source=lead.source,
        score=lead.score,
        status=lead.status,
        reasoning=lead.reasoning or "",
    )


def _to_detail(lead) -> LeadDetailResponse:
    bant = BantBreakdown(
        budget=lead.bant_budget_score,
        authority=lead.bant_authority_score,
        need=lead.bant_need_score,
        timeline=lead.bant_timeline_score,
        total=lead.bant_total_score,
        notes=lead.bant_notes,
    )
    meddic = MeddicBreakdown(
        metrics=lead.meddic_metrics_score,
        economic_buyer=lead.meddic_economic_buyer_score,
        decision_criteria=lead.meddic_decision_criteria_score,
        decision_process=lead.meddic_decision_process_score,
        identify_pain=lead.meddic_identify_pain_score,
        champion=lead.meddic_champion_score,
        total=lead.meddic_total_score,
        notes=lead.meddic_notes,
    )
    return LeadDetailResponse(
        id=lead.id,
        initials=lead.initials or "?",
        name=lead.name,
        company=lead.company,
        title=lead.title or "",
        email=lead.email or "",
        source=lead.source,
        score=lead.score,
        status=lead.status,
        reasoning=lead.reasoning or "",
        company_domain=lead.company_domain,
        company_size=lead.company_size,
        company_industry=lead.company_industry,
        company_revenue=lead.company_revenue,
        linkedin_url=lead.linkedin_url,
        phone=lead.phone,
        location=lead.location,
        icp_fit_score=lead.icp_fit_score,
        is_disqualified=(lead.is_disqualified == "true"),
        disqualify_reasons=lead.disqualify_reasons or [],
        bant=bant,
        meddic=meddic,
        email_subject=getattr(lead, "email_subject", None),
        email_body=getattr(lead, "email_body", None),
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=LeadListResponse)
async def list_leads(
    status: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    All leads for the current user, sorted by score desc.
    Used by /lead-generation and /qualification pages.
    Query params: ?status=Qualified  |  ?min_score=80
    """
    svc   = LeadsService(db)
    leads = await svc.list_leads(current_user.id, status=status, min_score=min_score)
    return LeadListResponse(leads=[_to_response(l) for l in leads], total=len(leads))


@router.post("/generate", response_model=GenerateLeadsResponse, status_code=201)
async def generate_leads(
    request: GenerateLeadsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    "Generate from ICP" button on the lead-generation page.
    Calls Apollo, scores every result with BANT+MEDDIC via Groq,
    and saves non-duplicate leads to the DB.
    """
    try:
        svc = LeadsService(db)
        created, skipped = await svc.generate_from_icp(
            user_id=current_user.id,
            team_id=current_user.team_id,
            request=request,
        )
        return GenerateLeadsResponse(
            success=True,
            message=f"Generated {len(created)} leads ({skipped} duplicates skipped).",
            created=len(created),
            skipped_duplicates=skipped,
            leads=[_to_response(l) for l in created],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Lead generation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/add", response_model=LeadDetailResponse, status_code=201)
async def add_manual_lead(
    payload: ManualLeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually add one lead. Apollo enrichment + BANT/MEDDIC scoring run automatically."""
    try:
        svc  = LeadsService(db)
        lead = await svc.create_manual_lead(
            user_id=current_user.id,
            team_id=current_user.team_id,
            payload=payload,
        )
        return _to_detail(lead)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Manual lead creation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{lead_id}", response_model=LeadDetailResponse)
async def get_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full detail including BANT/MEDDIC breakdown (for detail drawer/panel)."""
    svc  = LeadsService(db)
    lead = await svc.get_lead(current_user.id, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _to_detail(lead)


@router.patch("/{lead_id}/status", response_model=LeadResponse)
async def update_status(
    lead_id: UUID,
    payload: LeadStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generic status update. Covers all action buttons:
    Qualify / Discard / Draft / Send / Replied.
    """
    valid = {"New", "Analyzed", "Qualified", "Discarded", "Drafted", "Sent", "Replied"}
    if payload.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(valid)}")
    svc  = LeadsService(db)
    lead = await svc.update_status(current_user.id, lead_id, payload.status)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _to_response(lead)


@router.post("/{lead_id}/qualify", response_model=LeadResponse)
async def qualify_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Maps to the Qualify button / qualifyLead Redux action."""
    svc  = LeadsService(db)
    lead = await svc.qualify_lead(current_user.id, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _to_response(lead)


@router.post("/{lead_id}/discard", response_model=LeadResponse)
async def discard_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Maps to the Discard button / discardLead Redux action."""
    svc  = LeadsService(db)
    lead = await svc.discard_lead(current_user.id, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _to_response(lead)


@router.post("/{lead_id}/rescore", response_model=LeadDetailResponse)
async def rescore_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run BANT/MEDDIC after ICP changes or manual edits."""
    try:
        svc  = LeadsService(db)
        lead = await svc.rescore_lead(current_user.id, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return _to_detail(lead)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{lead_id}/outreach/generate", response_model=OutreachEmailResponse)
async def generate_outreach_email(
    lead_id: UUID,
    tone: str = Query("friendly", description="professional | friendly | direct"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate personalised outreach email via Groq.
    Sets lead.status = Drafted and saves draft on the lead.
    Maps to the Outreach page "Regenerate" button.
    """
    try:
        svc   = LeadsService(db)
        email = await svc.generate_outreach_email(
            user_id=current_user.id,
            lead_id=lead_id,
            sender_name=current_user.full_name,
            tone=tone,
        )
        if not email:
            raise HTTPException(status_code=404, detail="Lead not found")
        return OutreachEmailResponse(**email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Outreach email generation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/{lead_id}/outreach", response_model=LeadResponse)
async def save_outreach_draft(
    lead_id: UUID,
    payload: OutreachDraftSave,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist a manually edited outreach email draft. Sets status = Drafted."""
    svc  = LeadsService(db)
    lead = await svc.save_outreach_email(
        current_user.id, lead_id, payload.subject, payload.body
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _to_response(lead)


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard delete."""
    svc     = LeadsService(db)
    deleted = await svc.delete_lead(current_user.id, lead_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lead not found")
    return None