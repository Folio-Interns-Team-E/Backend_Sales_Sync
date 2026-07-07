from sqlalchemy import Column, String, DateTime, Integer, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship # 👈 Added relationship
from app.database import Base
import enum
import uuid

class LeadStatus(enum.Enum):
    NEW = "New"
    ANALYZED = "Analyzed"
    QUALIFIED = "Qualified"
    DISCARDED = "Discarded"
    DRAFTED = "Drafted"
    SENT = "Sent"
    REPLIED = "Replied"
    CONVERTED = "Converted"

class Lead(Base):
    __tablename__ = "leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # 🔗 This establishes the hard ForeignKey constraint to the 'teams' table id
    team_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("teams.id", ondelete="CASCADE"), # 👈 Ties it to teams table
        nullable=False, 
        index=True
    )
    
    # Core UI & Query Columns
    name = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    status = Column(String, default=LeadStatus.NEW.value, nullable=False, index=True)
    company_name = Column(String, nullable=True, index=True)
    job_title = Column(String, nullable=True)
    source = Column(String, nullable=True)
    score = Column(Integer, nullable=True)
    
    # AI Context Sandbox
    ai_context_data = Column(JSONB, default={}, nullable=False) 
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 🔄 Optional: ORM relationship back to the Team model
    team = relationship("Team", back_populates="leads")
    proposals = relationship("Proposal", back_populates="lead")
    meetings = relationship("Meeting", back_populates="lead")
    emails = relationship("Email", back_populates="lead")