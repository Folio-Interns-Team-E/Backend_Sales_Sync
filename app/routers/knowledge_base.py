from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.knowledge_base import KnowledgeAssetResponse
from app.schemas.common import ApiResponse
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-base", tags=["knowledge-base"])


@router.get("/", response_model=ApiResponse[list[KnowledgeAssetResponse]])
async def list_assets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeBaseService(db)
    assets = await service.list_assets(current_user.id)
    return ApiResponse(success=True, message="Assets fetched successfully", data=assets)


@router.get("/{asset_id}", response_model=ApiResponse[KnowledgeAssetResponse])
async def get_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeBaseService(db)
    asset = await service.get_asset(asset_id, current_user.id)
    return ApiResponse(success=True, message="Asset fetched successfully", data=asset)


@router.post("/upload", response_model=ApiResponse[KnowledgeAssetResponse], status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # comma-separated e.g. "sales,q3,proposal"
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate file type
    if file.content_type not in ["application/pdf"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported"
        )
    
    # Parse tags from comma-separated string
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    
    service = KnowledgeBaseService(db)
    asset = await service.upload_asset(
        current_user.id,
        title=title,
        file=file,
        description=description,
        tags=tag_list,
    )
    return ApiResponse(success=True, message="Asset uploaded successfully", data=asset)


@router.delete("/{asset_id}", response_model=ApiResponse[dict])
async def delete_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeBaseService(db)
    await service.delete_asset(asset_id, current_user.id)
    return ApiResponse(success=True, message="Asset deleted", data={})