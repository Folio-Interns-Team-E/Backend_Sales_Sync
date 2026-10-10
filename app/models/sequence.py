import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base


class Sequence(Base):
    __tablename__ = "sequences"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="Draft")
    timezone = Column(String(80), nullable=False, default="Asia/Karachi")
    daily_limit = Column(Integer, nullable=False, default=40)
    stop_on_reply = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (Index("ix_sequences_team_status", "team_id", "status"),)


class SequenceStep(Base):
    __tablename__ = "sequence_steps"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence_id = Column(UUID(as_uuid=True), ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    delay_days = Column(Integer, nullable=False, default=0)
    subject = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("sequence_id", "position", name="uq_sequence_step_position"),)


class SequenceEnrollment(Base):
    __tablename__ = "sequence_enrollments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence_id = Column(UUID(as_uuid=True), ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="Active")
    current_step = Column(Integer, nullable=False, default=0)
    next_send_at = Column(DateTime(timezone=True), nullable=True)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("sequence_id", "lead_id", name="uq_sequence_lead_enrollment"), Index("ix_sequence_enrollment_due", "status", "next_send_at"))
