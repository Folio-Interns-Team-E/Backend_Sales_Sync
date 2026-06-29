# File: backend/app/schemas/onboarding.py
# Copy this entire file as-is

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from typing import Optional
from datetime import datetime


class ICPCreate(BaseModel):
    """Schema for creating/updating ICP from user input"""
    product_name: Optional[str] = Field(None, description="Name of your product/service")
    product_description: str = Field(..., description="Detailed description of what your product/service does")
    company_description: Optional[str] = Field(None, description="Tell us about your company")
    target_market_description: str = Field(..., description="Describe your target market/ideal customer")
    target_regions: Optional[List[str]] = Field(default=[], description="Geographic regions you target")


class ICPResponse(BaseModel):
    """Schema for returning ICP data"""
    id: UUID
    user_id: UUID
    
    # User input
    product_name: Optional[str]
    product_description: str
    company_description: Optional[str]
    target_market_description: str
    
    # AI-generated fields
    target_industries: List[str]
    company_size_range: Optional[str]
    target_revenues: Optional[str]
    decision_maker_titles: List[str]
    pain_points: List[str]
    key_characteristics: List[str]
    target_regions: List[str]
    
    # Grok analysis
    grok_analysis: Optional[str]
    
    # Status
    onboarding_completed: str
    
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ICPUpdate(BaseModel):
    """Schema for updating ICP"""
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    company_description: Optional[str] = None
    target_market_description: Optional[str] = None
    target_regions: Optional[List[str]] = None


class OnboardingRequest(BaseModel):
    """User's onboarding input"""
    product_description: str = Field(..., description="What does your product do?")
    target_customer: str = Field(..., description="Who is your ideal customer?")
    product_name: Optional[str] = None


class OnboardingResponse(BaseModel):
    """Response with ICP generated from input"""
    success: bool
    message: str
    icp: Optional[ICPResponse] = None
    grok_analysis: Optional[str] = None


class SimpleICPResponse(BaseModel):
    """Simplified ICP response for quick fetch"""
    id: UUID
    target_industries: List[str]
    company_size_range: Optional[str]
    decision_maker_titles: List[str]
    pain_points: List[str]
    onboarding_completed: str

    class Config:
        from_attributes = True