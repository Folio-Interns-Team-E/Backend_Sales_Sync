import enum
import uuid
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base  # Adjust this import to match your project's setup

class ChatRole(str, enum.Enum):
    USER = "user"
    AI = "ai"

class ChatMessage(Base):
    """A flattened, simple log tracking every message sent between a user and the AI"""
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # 🔗 Contextual links
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # The teammate interacting with the AI
    
    # 🗣️ Tracks sender role: strictly 'user' or 'ai'
    sent_by = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    
    # ⚙️ Sandbox for metadata (tokens, model version, execution latency, etc.)
    metadata_log = Column(JSONB, default={}, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # 🛑 Postgres constraint to ensure message roles stay clean
    __table_args__ = (
        CheckConstraint("sent_by IN ('user', 'ai')", name="check_message_sender"),
    )

    # Relationship back to Team
    team = relationship("Team", back_populates="chat_messages")