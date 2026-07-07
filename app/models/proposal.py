from sqlalchemy import Column, String, DateTime, Text, Numeric, ForeignKey, CheckConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum
import uuid


class ProposalStatus(str, enum.Enum):
    DRAFT = "Draft"
    SENT = "Sent"
    UNDER_REVIEW = "Under Review"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"


class ProposalOutcome(str, enum.Enum):
    OPEN = "Open"
    WON = "Won"
    LOST = "Lost"


class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)

    company = Column(String, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    value = Column(Numeric(precision=12, scale=2), nullable=True)
    sources = Column(JSONB, default=[], nullable=False)

    status = Column(String, default=ProposalStatus.DRAFT.value, nullable=False, index=True)
    outcome = Column(String, default=ProposalOutcome.OPEN.value, nullable=False, index=True)

    sent_at = Column(DateTime(timezone=True), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('Draft', 'Sent', 'Under Review', 'Accepted', 'Rejected')", name="check_proposal_status"),
        CheckConstraint("outcome IN ('Open', 'Won', 'Lost')", name="check_proposal_outcome"),
    )

    team = relationship("Team", back_populates="proposals")
    lead = relationship("Lead", back_populates="proposals")
    revisions = relationship("ProposalRevision", back_populates="proposal", cascade="all, delete-orphan", order_by="desc(ProposalRevision.revision_num)")


class ProposalRevision(Base):
    __tablename__ = "proposal_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id = Column(UUID(as_uuid=True), ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_num = Column(Integer, nullable=False, default=1)
    title = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    value = Column(Numeric(precision=12, scale=2), nullable=True)
    edited_by = Column(UUID(as_uuid=True), nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    proposal = relationship("Proposal", back_populates="revisions")


class ProposalTemplate(Base):
    __tablename__ = "proposal_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    template_name = Column(String, nullable=False)
    company_name = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    sections = Column(JSONB, server_default='[]', nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    team = relationship("Team", back_populates="proposal_templates")
