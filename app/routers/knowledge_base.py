from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.knowledge_base import KnowledgeAssetCreate, KnowledgeAssetResponse
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


@router.post("/", response_model=ApiResponse[KnowledgeAssetResponse], status_code=201)
async def create_asset(
    payload: KnowledgeAssetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeBaseService(db)
    asset = await service.create_asset(
        current_user.id, payload.title, payload.type,
        payload.company, payload.date, payload.description,
        payload.file_url, payload.source_url
    )
    return ApiResponse(success=True, message="Asset created successfully", data=asset)


@router.delete("/{asset_id}", response_model=ApiResponse[dict])
async def delete_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeBaseService(db)
    await service.delete_asset(asset_id, current_user.id)
    return ApiResponse(success=True, message="Asset deleted", data={})
