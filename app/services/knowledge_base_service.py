import logging
import uuid
import re
import asyncio
from typing import Optional, List
from uuid import UUID
import boto3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status, UploadFile
from app.models.knowledge_base import KnowledgeAsset
from app.config import settings
from app.core.s3 import generate_presigned_url
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService

logger = logging.getLogger(__name__)

s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    region_name=settings.aws_region,
)


def _sanitize_filename(filename: str) -> str:
    filename = filename.replace("/", "").replace("\\", "")
    filename = re.sub(r"[^\w\.\-]", "_", filename)
    return filename


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _attach_presigned(self, asset):
        if asset.file_url and "amazonaws.com" in asset.file_url:
            asset.presigned_url = generate_presigned_url(asset.file_url)

    async def list_assets(self, team_id: UUID):
        query = (
            select(KnowledgeAsset)
            .where(KnowledgeAsset.team_id == team_id)
            .order_by(desc(KnowledgeAsset.created_at))
        )
        result = await self.db.execute(query)
        assets = result.scalars().all()
        from app.schemas.knowledge_base import KnowledgeAssetResponse
        data = [KnowledgeAssetResponse.model_validate(a).model_dump(mode="json") for a in assets]
        return data

    async def get_asset(self, asset_id: UUID, team_id: UUID):
        result = await self.db.execute(
            select(KnowledgeAsset).where(
                KnowledgeAsset.id == asset_id,
                KnowledgeAsset.team_id == team_id
            )
        )
        asset = result.scalar_one_or_none()
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge asset not found"
            )
        self._attach_presigned(asset)
        return asset

    async def upload_asset(
        self,
        team_id: UUID,
        title: str,
        file: UploadFile,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ):
        file_content = await file.read()
        file_size = len(file_content)

        safe_filename = _sanitize_filename(file.filename or "upload")
        unique_key = f"knowledge-assets/{team_id}/{uuid.uuid4()}/{safe_filename}"

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: s3_client.put_object(
                    Bucket=settings.aws_bucket_name,
                    Key=unique_key,
                    Body=file_content,
                    ContentType=file.content_type or "application/octet-stream",
                )
            )

            file_url = f"https://{settings.aws_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{unique_key}"
            file_type = file.content_type.split("/")[-1] if file.content_type else "pdf"

            asset = KnowledgeAsset(
                team_id=team_id,
                title=title,
                description=description,
                tags=tags or [],
                file_url=file_url,
                file_type=file_type,
                file_size=file_size,
                source_url=file_url,
                status="processing",
                chunk_count=0,
            )

            self.db.add(asset)
            await self.db.commit()
            await self.db.refresh(asset)

            rag_service = KnowledgeBaseRAGService(self.db)
            asset = await rag_service.index_asset(asset, file_content)

            logger.info(f"Asset {asset.id} uploaded successfully for team {team_id}")
            return asset

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to upload asset: {str(e)}")
            try:
                if 'asset' in locals():
                    asset.status = "failed"
                    asset.processing_error = str(e)
                    await self.db.commit()
            except Exception:
                logger.warning("Failed to persist KB indexing failure state")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file: {str(e)}",
            )

    async def update_asset(self, asset_id: UUID, team_id: UUID,
                            title: str | None = None,
                            description: str | None = None,
                            tags: list[str] | None = None):
        asset = await self.get_asset(asset_id, team_id)
        if title is not None:
            asset.title = title
        if description is not None:
            asset.description = description
        if tags is not None:
            asset.tags = tags
        await self.db.commit()
        await self.db.refresh(asset)
        self._attach_presigned(asset)
        return asset

    async def delete_asset(self, asset_id: UUID, team_id: UUID):
        asset = await self.get_asset(asset_id, team_id)

        rag_service = KnowledgeBaseRAGService(self.db)

        try:
            s3_key = asset.file_url.split(
                f"{settings.aws_bucket_name}.s3.{settings.aws_region}.amazonaws.com/"
            )[-1]

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: s3_client.delete_object(
                    Bucket=settings.aws_bucket_name,
                    Key=s3_key
                )
            )
        except Exception as e:
            logger.warning(f"Failed to delete S3 object: {str(e)}")

        try:
            await rag_service.delete_asset_index(asset)
        except Exception as e:
            logger.warning(f"Failed to delete Pinecone vectors: {str(e)}")

        await self.db.delete(asset)
        await self.db.commit()
