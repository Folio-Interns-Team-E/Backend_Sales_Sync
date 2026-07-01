# File: backend/app/schemas/onboarding.py
# UPDATED VERSION - Replace existing file

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class OnboardingRequest(BaseModel):
    """
    Schema for frontend onboarding form.
    Accepts camelCase from React frontend and converts to backend format.
    """
    product_name: Optional[str] = Field(None, alias="productName", description="Name of your product")
    product_description: str = Field(..., alias="productDescription", description="What does your product do?")
    target_customer: str = Field(..., alias="targetCustomer", description="Who is your target customer?")
    goals: str = Field(..., description="What should the sales copilot optimize for?")
    
    model_config = ConfigDict(populate_by_name=True)


class ICPCreate(BaseModel):
    """Schema for creating/updating ICP from user input"""
    product_name: Optional[str] = Field(None, description="Name of your product/service")
    product_description: str = Field(..., description="Detailed description of what your product/service does")
    target_market_description: str = Field(..., description="Describe your target market/ideal customer")
    goals: str = Field(..., description="What should the sales copilot optimize for?")
    company_description: Optional[str] = Field(None, description="Tell us about your company")
    target_regions: Optional[List[str]] = Field(default=[], description="Geographic regions you target")


class ICPResponse(BaseModel):
    """Schema for returning ICP data to frontend"""
    id: UUID
    user_id: UUID
    
    # User input
    product_name: Optional[str]
    product_description: str
    target_market_description: str
    goals: str
    company_description: Optional[str]
    
    # AI-generated fields
    target_industries: List[str]
    company_size_range: Optional[str]
    target_revenues: Optional[str]
    decision_maker_titles: List[str]
    pain_points: List[str]
    key_characteristics: List[str]
    target_regions: List[str]
    
    # ICP Summary for preview
    icp_summary: List[str]
    
    # Grok analysis
    grok_analysis: Optional[str]
    
    # Status
    onboarding_completed: str
    
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OnboardingResponse(BaseModel):
    """Response with ICP generated from input - matches frontend expectations"""
    success: bool
    message: str
    icp: Optional[ICPResponse] = None
    
    model_config = ConfigDict(from_attributes=True)


class ICPUpdate(BaseModel):
    """Schema for updating ICP"""
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    target_market_description: Optional[str] = None
    goals: Optional[str] = None
    company_description: Optional[str] = None
    target_regions: Optional[List[str]] = None
    
    model_config = ConfigDict(populate_by_name=True)


class SimpleICPResponse(BaseModel):
    """Simplified ICP response for quick fetch"""
    id: UUID
    target_industries: List[str]
    company_size_range: Optional[str]
    decision_maker_titles: List[str]
    pain_points: List[str]
    icp_summary: List[str]
    onboarding_completed: str

    model_config = ConfigDict(from_attributes=True)