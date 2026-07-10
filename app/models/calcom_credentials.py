import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class CalComIntegration(Base):
    __tablename__ = "calcom_integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # Store API key encrypted. Event type ID can be plain string/int.
    encrypted_api_key = Column(String, nullable=False)
    event_type_id = Column(String, nullable=False) 

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,  # Kept nullable for now
        index=True,
    )

    # Relationship back to the User
    user = relationship("User", back_populates="calcom_integration")
    team = relationship("Team", back_populates="calcom_integrations")
    