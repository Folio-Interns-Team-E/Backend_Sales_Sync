from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class OnboardingRequest(BaseModel):
    product_name: Optional[str] = Field(None, alias="productName")
    product_description: str = Field(..., alias="productDescription")
    target_customer: str = Field(..., alias="targetCustomer")
    goals: str = Field(...)

    model_config = ConfigDict(populate_by_name=True)


class OnboardingResponse(BaseModel):
    success: bool
    message: str
    icp: str = ""
    completed: bool = False

    model_config = ConfigDict(from_attributes=True)
