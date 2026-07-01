from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Integer, JSON, Float
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import enum


class LeadStatus(str, enum.Enum):
    new = "New"
    analyzed = "Analyzed"
    qualified = "Qualified"
    discarded = "Discarded"
    drafted = "Drafted"
    sent = "Sent"
    replied = "Replied"


class LeadSource(str, enum.Enum):
    apollo = "Apollo"
    linkedin = "LinkedIn"
    crunchbase = "Crunchbase"
    manual = "Manual"
    custom_url = "Custom URL"


class Lead(Base):
    """
    A prospect surfaced for a user/team, enriched via Apollo and scored
    against the user's ICP using BANT + MEDDIC.
    """

    __tablename__ = "leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Ownership
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=True, index=True)
    icp_id = Column(UUID(as_uuid=True), ForeignKey("icps.id"), nullable=True)

    # Core identity (matches frontend Lead type 1:1)
    name = Column(String, nullable=False)
    company = Column(String, nullable=False)
    title = Column(String, nullable=True)
    email = Column(String, nullable=True, index=True)
    source = Column(String, nullable=False, default=LeadSource.apollo.value)
    score = Column(Integer, nullable=False, default=0)  # 0-100, shown directly in UI
    status = Column(String, nullable=False, default=LeadStatus.new.value)
    reasoning = Column(Text, nullable=True)  # short human-readable summary for the UI card

    # Firmographics (from Apollo enrichment)
    company_domain = Column(String, nullable=True)
    company_size = Column(String, nullable=True)
    company_industry = Column(String, nullable=True)
    company_revenue = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    location = Column(String, nullable=True)
    apollo_person_id = Column(String, nullable=True, index=True)
    apollo_org_id = Column(String, nullable=True)
    raw_apollo_data = Column(JSON, nullable=True)

    # --- BANT scoring (Budget, Authority, Need, Timeline) ---
    bant_budget_score = Column(Integer, nullable=True)       # 0-100
    bant_authority_score = Column(Integer, nullable=True)    # 0-100
    bant_need_score = Column(Integer, nullable=True)         # 0-100
    bant_timeline_score = Column(Integer, nullable=True)     # 0-100
    bant_total_score = Column(Integer, nullable=True)        # weighted avg of the 4 above
    bant_notes = Column(JSON, nullable=True)                 # {"budget": "...", "authority": "...", ...}

    # --- MEDDIC scoring (Metrics, Economic Buyer, Decision Criteria, Decision Process, Identify Pain, Champion) ---
    meddic_metrics_score = Column(Integer, nullable=True)
    meddic_economic_buyer_score = Column(Integer, nullable=True)
    meddic_decision_criteria_score = Column(Integer, nullable=True)
    meddic_decision_process_score = Column(Integer, nullable=True)
    meddic_identify_pain_score = Column(Integer, nullable=True)
    meddic_champion_score = Column(Integer, nullable=True)
    meddic_total_score = Column(Integer, nullable=True)
    meddic_notes = Column(JSON, nullable=True)

    # --- Disqualification (rules layer, runs before AI scoring) ---
    is_disqualified = Column(String, default="false")  # "true"/"false" (kept simple, no separate bool migration headaches)
    disqualify_reasons = Column(ARRAY(String), default=[])

    # --- ICP fit (rules layer, independent of BANT/MEDDIC) ---
    icp_fit_score = Column(Integer, nullable=True)  # 0-100, how well firmographics match the ICP

    # Raw AI response for debugging / re-display
    grok_scoring_response = Column(JSON, nullable=True)

    # Saved outreach draft generated from Grok or edited by the user.
    email_subject = Column(Text, nullable=True)
    email_body = Column(Text, nullable=True)

    initials = Column(String, nullable=True)  # cached, derived from name on save

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    team = relationship("Team")
    icp = relationship("ICP")