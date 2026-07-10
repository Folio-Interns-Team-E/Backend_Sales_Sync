from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import secrets
import enum




class Team(Base):
    __tablename__ = "teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)

    icp = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    invite_code = Column(
        String,
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(8)
    )
    

    stripe_customer_id = Column(String, nullable=True, unique=True)
    
    subscriptions = relationship("Subscription", back_populates="team", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="team", cascade="all, delete-orphan")

  
    members = relationship(
        "TeamMember",
        back_populates="team",
        cascade="all, delete-orphan"
    )
    leads = relationship("Lead", back_populates="team")
  

    proposal_templates = relationship("ProposalTemplate", back_populates="team")
    knowledge_assets = relationship("KnowledgeAsset", back_populates="team")
    chat_messages = relationship("ChatMessage", back_populates="team", cascade="all, delete-orphan")

    google_credentials = relationship("GoogleCredentials", back_populates="team", cascade="all, delete-orphan")
    calcom_integrations = relationship("CalComIntegration", back_populates="team", cascade="all, delete-orphan")



    