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
   
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)

    template_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("proposal_templates.id", ondelete="SET NULL"), 
        nullable=True, 
        index=True
    )

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
    file_url = Column(String, nullable=False)   # S3 URL
    file_type = Column(String, nullable=True)   # pdf, docx etc
    file_size = Column(Integer, nullable=True)

    ai_metadata = Column(JSONB, default={}, nullable=False)

    lead = relationship("Lead", back_populates="proposals")
    version = Column(Integer, nullable=False, default=1)
    template = relationship("ProposalTemplate", back_populates="proposals")


class ProposalTemplate(Base):
    __tablename__ = "proposal_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    template_name = Column(String, nullable=False)
    file_url = Column(String, nullable=False)   # S3 URL
    file_type = Column(String, nullable=True)   # pdf, docx etc
    file_size = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    team = relationship("Team", back_populates="proposal_templates")
    proposals = relationship("Proposal", back_populates="template")
