# File: backend/app/models/icp.py
# UPDATED VERSION - Replace existing file

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid


class ICP(Base):
    """
    Ideal Customer Profile - stores the user's ICP generated from their product description
    ICP = Ideal Customer Profile (the type of customer they want to target)
    """

    __tablename__ = "icps"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    
    # Product & Company Info (what user described)
    product_name = Column(String, nullable=True)
    product_description = Column(Text, nullable=True)
    company_description = Column(Text, nullable=True)
    target_market_description = Column(Text, nullable=True)
    goals = Column(Text, nullable=True)  # NEW: What should the sales copilot optimize for?
    
    # Generated ICP Fields (from Grok)
    target_industries = Column(ARRAY(String), default=[])  # e.g., ["Technology", "SaaS", "B2B"]
    company_size_range = Column(String, nullable=True)  # e.g., "10-50" or "50-200" or "200-500"
    target_revenues = Column(String, nullable=True)  # e.g., "$1M-10M" or "$10M-50M"
    decision_maker_titles = Column(ARRAY(String), default=[])  # e.g., ["CTO", "VP Engineering", "Tech Lead"]
    pain_points = Column(ARRAY(String), default=[])  # e.g., ["Lead generation", "Sales automation"]
    key_characteristics = Column(ARRAY(String), default=[])  # Other unique traits
    
    # Geography/Location
    target_regions = Column(ARRAY(String), default=[])  # e.g., ["North America", "Europe"]
    
    # ICP Summary (for frontend display) - NEW
    icp_summary = Column(ARRAY(String), default=[])  # List of 5-7 key ICP characteristics for preview
    
    # Grok Response (raw AI data)
    grok_full_response = Column(JSON, nullable=True)  # Store full Grok response for debugging
    grok_analysis = Column(Text, nullable=True)  # Full analysis from Grok
    
    # Metadata
    onboarding_completed = Column(String, default="incomplete")  # "incomplete", "in_progress", "completed"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="icp")