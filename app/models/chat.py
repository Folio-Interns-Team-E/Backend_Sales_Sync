import enum
import uuid
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class ChatRole(str, enum.Enum):
    USER = "user"
    AI = "ai"


class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chat_name = Column(String, nullable=False, default="New Chat")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    team = relationship("Team", back_populates="chats")
    messages = relationship("ChatMessage", back_populates="chat", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

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

    chat = relationship("Chat", back_populates="messages")
    team = relationship("Team", back_populates="chat_messages")
    user = relationship("User", back_populates="chat_messages")
