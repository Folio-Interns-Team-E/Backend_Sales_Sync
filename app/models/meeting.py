from sqlalchemy import Column, String, DateTime, Date, Time, Text, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum
import uuid

class MeetingStatus(str, enum.Enum):
    SCHEDULED = "Scheduled"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NO_SHOW = "No-Show"

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


   
    
    
    # 🔗 Links to the lead (Using SET NULL so if a lead is deleted, the historical meeting records remain)
    lead_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("leads.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )

    # 📅 Scheduling
    date = Column(Date, nullable=False, index=True) # Indexed for calendar views
    time = Column(Time, nullable=False)
    timezone = Column(String, default="UTC", nullable=False)
    calendar_event_id = Column(String, nullable=True)

    # 📝 Content & AI Input Sandbox
    agenda = Column(JSONB, server_default='[]', nullable=False)      # e.g., ["Intro", "Demo"]

    notes = Column(Text, nullable=True)

    # 📊 Status Tracking with constraint
    status = Column(
        String, 
        default=MeetingStatus.SCHEDULED.value, 
        nullable=False, 
        index=True
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 🛑 Postgres-level Check Constraint to guarantee status values match your business rules
    __table_args__ = (
        CheckConstraint(
            f"status IN ('Scheduled', 'Live', 'Completed', 'Cancelled', 'No-Show')",
            name="check_meeting_status"
        ),
    )

    # 🔄 Relationships
   
    lead = relationship("Lead", back_populates="meetings")