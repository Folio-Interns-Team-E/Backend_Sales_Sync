# File: backend/app/routers/onboarding.py
# Copy this entire file as-is

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.onboarding import (
    OnboardingRequest,
    OnboardingResponse,
    ICPResponse,
    ICPUpdate,
)
from app.services.onboarding_service import OnboardingService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/icp", response_model=OnboardingResponse, status_code=status.HTTP_201_CREATED)
async def create_icp(
    request: OnboardingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create or update ICP by describing product and target customer.
    System calls Grok to generate detailed ICP analysis.
    
    **Request Body:**
    - `product_description`: What your product does (required)
    - `target_customer`: Description of ideal customer (required)
    - `product_name`: Name of your product (optional)
    
    **Response:**
    - Generated ICP with industries, company size, decision makers, pain points, etc.
    """
    try:
        service = OnboardingService(db)
        
        icp = await service.create_or_update_icp(
            user_id=current_user.id,
            product_description=request.product_description,
            target_market_description=request.target_customer,
            product_name=request.product_name
        )
        
        logger.info(f"Created/Updated ICP for user {current_user.id}")
        
        return OnboardingResponse(
            success=True,
            message="ICP generated successfully",
            icp=ICPResponse.from_orm(icp),
            grok_analysis=icp.grok_analysis
        )
    
    except ValueError as e:
        logger.error(f"ValueError in create_icp: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating ICP: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ICP: {str(e)}"
        )


@router.get("/icp", response_model=ICPResponse)
async def get_icp(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Fetch current ICP for authenticated user.
    
    **Response:**
    - Complete ICP data including:
      - Target industries
      - Company size range
      - Decision maker titles
      - Pain points
      - Grok analysis
    """
    service = OnboardingService(db)
    icp = await service.get_icp(current_user.id)
    
    if not icp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICP not found. Please create one by POSTing to /onboarding/icp"
        )
    
    return ICPResponse.from_orm(icp)


@router.put("/icp", response_model=ICPResponse)
async def update_icp(
    icp_update: ICPUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update ICP with new information.
    System will re-analyze with Grok.
    
    **Request Body (all optional):**
    - `product_name`: Updated product name
    - `product_description`: Updated product description
    - `company_description`: Updated company description
    - `target_market_description`: Updated target market
    - `target_regions`: List of target regions
    
    **Response:**
    - Updated ICP with regenerated analysis
    """
    try:
        service = OnboardingService(db)
        updated_icp = await service.update_icp(current_user.id, icp_update)
        
        if not updated_icp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ICP not found"
            )
        
        logger.info(f"Updated ICP for user {current_user.id}")
        return ICPResponse.from_orm(updated_icp)
    
    except ValueError as e:
        logger.error(f"ValueError in update_icp: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error updating ICP: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update ICP: {str(e)}"
        )


@router.get("/status", response_model=dict)
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get user's onboarding status.
    
    **Response:**
    - `status`: "not_started", "in_progress", or "completed"
    - `completed`: Boolean flag
    - `icp`: ICP data if exists
    """
    service = OnboardingService(db)
    status_data = await service.get_onboarding_status(current_user.id)
    
    return {
        "status": status_data["status"],
        "completed": status_data["completed"],
        "icp": ICPResponse.from_orm(status_data["icp"]) if status_data["icp"] else None
    }


@router.delete("/icp", status_code=status.HTTP_204_NO_CONTENT)
async def delete_icp(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete user's ICP and start onboarding over.
    """
    service = OnboardingService(db)
    deleted = await service.delete_icp(current_user.id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICP not found"
        )
    
    logger.info(f"Deleted ICP for user {current_user.id}")
    return None