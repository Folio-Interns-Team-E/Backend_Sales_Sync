import enum
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class OpportunityStage(str, enum.Enum):
    PROSPECTING = "Prospecting"
    QUALIFICATION = "Qualification"
    PROPOSAL = "Proposal"
    NEGOTIATION = "Negotiation"
    CLOSED_WON = "Closed Won"
    CLOSED_LOST = "Closed Lost"


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(200), nullable=False)
    company_name = Column(String(200), nullable=False)
    stage = Column(String(32), nullable=False, default=OpportunityStage.PROSPECTING.value)
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="USD")
    probability = Column(Integer, nullable=False, default=10)
    expected_close_date = Column(Date, nullable=True)
    loss_reason = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    team = relationship("Team", back_populates="opportunities")
    lead = relationship("Lead", back_populates="opportunities")
    owner = relationship("User", back_populates="owned_opportunities")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_opportunities_amount_nonnegative"),
        CheckConstraint("probability >= 0 AND probability <= 100", name="ck_opportunities_probability_range"),
        Index("ix_opportunities_team_stage", "team_id", "stage"),
        Index("ix_opportunities_team_owner", "team_id", "owner_id"),
    )
