from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import enum

class EmailStatus(enum.Enum):
    DRAFT = "draft"
    SENT = "sent"

class Email(Base):
    __tablename__ = "emails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
  
    
    # 🔗 Links this email directly to the recipient lead
    lead_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("leads.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )

    # ✉️ Core Email Data
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False) # Stores the full generated HTML or plain text body
    
    # 📊 Status Tracking (e.g., 'draft', 'sent', 'delivered', 'bounced')
    status = Column(Enum(EmailStatus), default=EmailStatus.DRAFT, nullable=False, index=True)
    
    # 🧠 AI Metadata Sandbox 
    # Great for storing: {"prompt_version": "v2", "temperature": 0.7, "model_used": "grok-2"}
    ai_metadata = Column(JSONB, default={}, nullable=False)
    
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # 🔄 Relationships for easy ORM querying
   
    lead = relationship("Lead", back_populates="emails")