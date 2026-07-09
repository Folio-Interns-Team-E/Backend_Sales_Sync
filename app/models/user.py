from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    email_verified = Column(Boolean, nullable=False, default=False)
    hashed_password = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 🔥 relationship (user can be in many teams)
    teams = relationship(
        "TeamMember",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    chat_messages = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")
    google_credentials = relationship("GoogleCredentials", back_populates="user", uselist=False, cascade="all, delete-orphan")
    calcom_integration = relationship("CalComIntegration", back_populates="user", uselist=False, cascade="all, delete-orphan")

