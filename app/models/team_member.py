from sqlalchemy import Column, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid

from app.models.user import UserRole


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)

    role = Column(Enum(UserRole), default=UserRole.manager)

    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    # 🔥 relationships
    user = relationship("User", back_populates="teams")
    team = relationship("Team", back_populates="members")