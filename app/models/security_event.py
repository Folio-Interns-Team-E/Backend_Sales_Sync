"""Account-private security events; deliberately no free-form metadata or secrets."""
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class SecurityAction(str, enum.Enum):
    password_login = "password_login"
    password_reset = "password_reset"
    google_login = "google_login"
    github_login = "github_login"
    google_linked = "google_linked"
    github_linked = "github_linked"


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action = Column(Enum(SecurityAction, native_enum=False, create_constraint=True, name="security_action"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_security_events_user_created_id", "user_id", "created_at", "id"),)
