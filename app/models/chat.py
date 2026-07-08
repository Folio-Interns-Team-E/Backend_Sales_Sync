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
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sent_by = Column(String, nullable=False)
    content = Column(Text, nullable=False)

    metadata_log = Column(JSONB, nullable=False, default=dict)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "sent_by IN ('user', 'ai')",
            name="check_message_sender",
        ),
    )

    team = relationship("Team", back_populates="chat_messages")
    user = relationship("User", back_populates="chat_messages")