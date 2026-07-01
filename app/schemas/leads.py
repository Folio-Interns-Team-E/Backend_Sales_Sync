from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


# ─────────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────────

class GenerateLeadsRequest(BaseModel):
    """Kick off Apollo lead generation from the current user ICP."""
    limit: int = Field(25, ge=1, le=100)
    locations: Optional[List[str]] = None        # overrides ICP target_regions
    extra_titles: Optional[List[str]] = None     # appended to ICP decision_maker_titles


class ManualLeadCreate(BaseModel):
    """Add one lead by hand (Apollo enrichment attempted automatically)."""
    name: str
    company: str
    title: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    company_domain: Optional[str] = None
    source: str = "Manual"


class LeadStatusUpdate(BaseModel):
    """Patch the status of a single lead."""
    status: str = Field(
        ...,
        description="One of: New, Analyzed, Qualified, Discarded, Drafted, Sent, Replied",
    )


class OutreachDraftSave(BaseModel):
    """Save the AI-drafted outreach email against the lead."""
    subject: str
    body: str


# ─────────────────────────────────────────────────────────────────────────────
# Responses
# ─────────────────────────────────────────────────────────────────────────────

class LeadResponse(BaseModel):
    """
    Primary list-view shape.
    Field names match the frontend `Lead` TypeScript type exactly so the
    Redux store can consume the response with zero mapping.
    """
    id: UUID
    initials: str
    name: str
    company: str
    title: str = ""
    email: str = ""
    source: str
    score: int
    status: str
    reasoning: str = ""

    model_config = ConfigDict(from_attributes=True)


class BantBreakdown(BaseModel):
    budget: Optional[int] = None
    authority: Optional[int] = None
    need: Optional[int] = None
    timeline: Optional[int] = None
    total: Optional[int] = None
    notes: Optional[Dict[str, Any]] = None


class MeddicBreakdown(BaseModel):
    metrics: Optional[int] = None
    economic_buyer: Optional[int] = None
    decision_criteria: Optional[int] = None
    decision_process: Optional[int] = None
    identify_pain: Optional[int] = None
    champion: Optional[int] = None
    total: Optional[int] = None
    notes: Optional[Dict[str, Any]] = None


class LeadDetailResponse(LeadResponse):
    """
    Full detail view returned by GET /leads/{id}.
    Contains all enrichment + BANT/MEDDIC breakdown for the detail drawer.
    """
    company_domain: Optional[str] = None
    company_size: Optional[str] = None
    company_industry: Optional[str] = None
    company_revenue: Optional[str] = None
    linkedin_url: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None

    icp_fit_score: Optional[int] = None
    is_disqualified: bool = False
    disqualify_reasons: List[str] = []

    bant: Optional[BantBreakdown] = None
    meddic: Optional[MeddicBreakdown] = None

    email_subject: Optional[str] = None
    email_body: Optional[str] = None

    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LeadListResponse(BaseModel):
    leads: List[LeadResponse]
    total: int


class GenerateLeadsResponse(BaseModel):
    success: bool
    message: str
    created: int
    skipped_duplicates: int = 0
    leads: List[LeadResponse]


class OutreachEmailResponse(BaseModel):
    subject: str
    body: str