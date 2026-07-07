from sqlalchemy import Column, String, DateTime, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid


class KnowledgeAsset(Base):
    __tablename__ = "knowledge_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    type = Column(String, nullable=False, default="Document")
    company = Column(String, nullable=True)
    date = Column(Date, nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(JSONB, default=[], nullable=False)
    file_url = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    file_type = Column(String, nullable=True)
    file_size = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="Processing")
    embedding_id = Column(String, nullable=True)
    chunk_count = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    team = relationship("Team", back_populates="knowledge_assets")
