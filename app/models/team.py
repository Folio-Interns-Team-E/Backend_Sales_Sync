from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import secrets


class Team(Base):
    __tablename__ = "teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 🔥 invite system
    invite_code = Column(
        String,
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(8)
    )

    # 🔥 members via relationship table
    members = relationship(
        "TeamMember",
        back_populates="team",
        cascade="all, delete-orphan"
    )