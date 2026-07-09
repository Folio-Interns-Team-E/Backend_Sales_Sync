from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.onboarding import OnboardingRequest, OnboardingResponse
from app.schemas.common import ApiResponse
from app.services.onboarding_service import OnboardingService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/icp", response_model=ApiResponse[OnboardingResponse], status_code=201)
async def submit_onboarding(
    request: OnboardingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OnboardingService(db)
    icp_text = await service.submit_onboarding(
        current_user.id,
        request.product_name,
        request.product_description,
        request.target_customer,
        request.goals,
    )
    return ApiResponse(
        success=True,
        message="ICP saved successfully",
        data=OnboardingResponse(success=True, message="ICP saved", icp=icp_text, completed=True),
    )


@router.get("/status", response_model=ApiResponse[OnboardingResponse])
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OnboardingService(db)
    status_data = await service.get_onboarding(current_user.id)
    return ApiResponse(
        success=True,
        message="Onboarding status fetched",
        data=OnboardingResponse(
            success=True,
            message="Onboarding status",
            icp=status_data["icp"],
            completed=status_data["completed"],
        ),
    )

@router.get("/icp", response_model=ApiResponse[OnboardingResponse])
async def get_icp(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OnboardingService(db)
    status_data = await service.get_onboarding(current_user.id)
    return ApiResponse(
        success=True,
        message="ICP fetched successfully",
        data=OnboardingResponse(
            success=True,
            message="ICP fetched",
            icp=status_data["icp"],
            completed=status_data["completed"],
        ),
    )


@router.put("/icp", response_model=ApiResponse[OnboardingResponse])
async def update_icp(
    request: OnboardingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = OnboardingService(db)
    icp_text = await service.update_onboarding(
        current_user.id,
        request.product_name,
        request.product_description,
        request.target_customer,
        request.goals,
    )
    return ApiResponse(
        success=True,
        message="ICP updated successfully",
        data=OnboardingResponse(
            success=True,
            message="ICP updated",
            icp=icp_text,
            completed=True,
        ),
    )