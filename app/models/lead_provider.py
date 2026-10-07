import uuid
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base


class LeadProviderCredential(Base):
    __tablename__ = "lead_provider_credentials"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False)
    encrypted_api_key = Column(String, nullable=False)
    monthly_limit = Column(Integer, nullable=False, default=100)
    used_this_month = Column(Integer, nullable=False, default=0)
    usage_month = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("team_id", "provider", name="uq_lead_provider_team_provider"),)
