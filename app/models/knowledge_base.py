from sqlalchemy import Column, String, DateTime, Date, Text, ForeignKey, Integer
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
    description = Column(Text, nullable=True)
    tags = Column(JSONB, default=[], nullable=False)
    
    # S3 storage
    file_url = Column(String, nullable=False)   # S3 URL
    file_type = Column(String, nullable=True)   # pdf, docx etc
    file_size = Column(Integer, nullable=True)  # bytes
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    team = relationship("Team", back_populates="knowledge_assets")