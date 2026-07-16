from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Integer
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
    tags = Column(JSONB, default=list, nullable=False)
    
    # S3 storage
    file_url = Column(String, nullable=False)   # S3 URL
    file_type = Column(String, nullable=True)   # pdf, docx etc
    file_size = Column(Integer, nullable=True)  # bytes
    source_url = Column(String, nullable=True)

    # RAG/indexing state
    status = Column(String, nullable=False, default="processing")
    embedding_id = Column(String, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    indexed_at = Column(DateTime(timezone=True), nullable=True)
    processing_error = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    team = relationship("Team", back_populates="knowledge_assets")
    chunks = relationship(
        "KnowledgeAssetChunk",
        back_populates="asset",
        cascade="all, delete-orphan",
    )


class KnowledgeAssetChunk(Base):
    __tablename__ = "knowledge_asset_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    pinecone_vector_id = Column(String, nullable=False, unique=True, index=True)
    token_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    team = relationship("Team", back_populates="knowledge_asset_chunks")
    asset = relationship("KnowledgeAsset", back_populates="chunks")