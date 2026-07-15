import hashlib
import io
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.knowledge_base import KnowledgeAsset, KnowledgeAssetChunk
from app.models.team import Team
from app.models.team_member import TeamMember


logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
EMBEDDING_DIMENSION = 256


class KnowledgeBaseRAGService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._pinecone_client = None
        self._pinecone_index = None

    async def _get_user_team(self, user_id: UUID) -> Team:
        result = await self.db.execute(
            select(TeamMember).where(TeamMember.user_id == user_id)
        )
        membership = result.scalar_one_or_none()
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no team",
            )

        result = await self.db.execute(
            select(Team).where(Team.id == membership.team_id)
        )
        team = result.scalar_one_or_none()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found",
            )
        return team

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return TOKEN_PATTERN.findall(text.lower())

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 2200, overlap: int = 300) -> list[str]:
        words = text.split()
        if not words:
            return []

        chunk_size = max(chunk_size, 200)
        overlap = max(min(overlap, chunk_size - 1), 0)
        step = max(chunk_size - overlap, 1)

        chunks: list[str] = []
        for start in range(0, len(words), step):
            chunk = words[start : start + chunk_size]
            if chunk:
                chunks.append(" ".join(chunk))
        return chunks

    @staticmethod
    def _embed_text(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
        tokens = KnowledgeBaseRAGService._tokenize(text)
        if not tokens:
            return [0.0] * dimension

        counts = Counter(tokens)
        vector = [0.0] * dimension
        for token, weight in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, byteorder="big") % dimension
            vector[index] += float(weight)

        norm = sum(value * value for value in vector) ** 0.5
        if norm:
            vector = [value / norm for value in vector]
        return vector

    @staticmethod
    def _extract_pdf_text(file_content: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PDF indexing requires the pypdf package.",
            ) from exc

        reader = PdfReader(io.BytesIO(file_content))
        pages: list[str] = []
        for page in reader.pages:
            extracted = page.extract_text() or ""
            if extracted.strip():
                pages.append(extracted)
        return "\n\n".join(pages).strip()

    def _get_pinecone_client(self):
      if self._pinecone_client is not None:
        return self._pinecone_client

      from pinecone import Pinecone

      client = Pinecone(api_key=settings.pinecone_api_key)

      indexes = client.list_indexes()

      print("========== PINECONE INDEXES ==========")
      print(indexes)
      print("Looking for:", settings.pinecone_index_name)
      print("======================================")

      self._pinecone_client = client
      return client
    def _get_pinecone_index(self):
      if self._pinecone_index:
        return self._pinecone_index

      client = self._get_pinecone_client()

      print("Opening index:", settings.pinecone_index_name)

      self._pinecone_index = client.Index(settings.pinecone_index_name)

      return self._pinecone_index

    async def _pinecone_upsert(self, vectors, namespace):
     print("UPSERT")
     print("Namespace:", namespace)
     print("Vectors:", len(vectors))

     index = self._get_pinecone_index()

     await self.db.run_sync(
        lambda _: index.upsert(
            vectors=vectors,
            namespace=namespace,
        )
     )

    async def _pinecone_query(self, vector: list[float], namespace: str, top_k: int) -> dict[str, Any]:
        index = self._get_pinecone_index()
        return await self.db.run_sync(
            lambda _: index.query(
                vector=vector,
                namespace=namespace,
                top_k=top_k,
                include_metadata=True,
            )
        )

    async def _pinecone_delete_asset(self, namespace: str, asset_id: UUID):
      index = self._get_pinecone_index()

      try:
        await self.db.run_sync(
            lambda _: index.delete(
                namespace=namespace,
                filter={"asset_id": str(asset_id)},
            )
        )
      except Exception as e:
        if "Namespace not found" in str(e):
            logger.info(
                f"Namespace {namespace} does not exist yet. Nothing to delete."
            )
            return

        raise
    async def index_asset(self, asset: KnowledgeAsset, file_content: bytes) -> KnowledgeAsset:
        text = self._extract_pdf_text(file_content)
        if not text:
            asset.status = "failed"
            asset.processing_error = "No extractable text found in PDF."
            await self.db.commit()
            await self.db.refresh(asset)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No extractable text found in the uploaded PDF.",
            )

        chunks = self._chunk_text(text)
        if not chunks:
            asset.status = "failed"
            asset.processing_error = "Unable to split the document into chunks."
            await self.db.commit()
            await self.db.refresh(asset)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to split the uploaded document into searchable chunks.",
            )

        namespace = str(asset.team_id)

        await self.db.execute(
            delete(KnowledgeAssetChunk).where(KnowledgeAssetChunk.asset_id == asset.id)
        )
        await self._pinecone_delete_asset(namespace, asset.id)

        chunk_rows: list[KnowledgeAssetChunk] = []
        vectors: list[dict[str, Any]] = []
        for chunk_index, chunk_text in enumerate(chunks):
            vector_id = f"{asset.id}:{chunk_index}"
            vectors.append(
                {
                    "id": vector_id,
                    "values": self._embed_text(chunk_text),
                    "metadata": {
                        "asset_id": str(asset.id),
                        "asset_title": asset.title,
                        "chunk_index": chunk_index,
                        "source_url": asset.file_url,
                    },
                }
            )
            chunk_rows.append(
                KnowledgeAssetChunk(
                    team_id=asset.team_id,
                    asset_id=asset.id,
                    chunk_index=chunk_index,
                    content=chunk_text,
                    pinecone_vector_id=vector_id,
                    token_count=len(self._tokenize(chunk_text)),
                )
            )

        self.db.add_all(chunk_rows)
        await self._pinecone_upsert(vectors, namespace)

        asset.status = "ready"
        asset.embedding_id = f"{asset.id}"
        asset.chunk_count = len(chunks)
        asset.indexed_at = datetime.now(timezone.utc)
        asset.processing_error = None
        asset.source_url = asset.file_url

        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    async def delete_asset_index(self, asset: KnowledgeAsset) -> None:
        namespace = str(asset.team_id)
        await self._pinecone_delete_asset(namespace, asset.id)

    async def search(self, team_id: UUID, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        namespace = str(team_id)
        pinecone_result = await self._pinecone_query(
            vector=self._embed_text(query),
            namespace=namespace,
            top_k=max(limit, 1),
        )

        matches = getattr(pinecone_result, "matches", None) or pinecone_result.get("matches", [])
        if not matches:
            return []

        vector_ids = [match.get("id") for match in matches if match.get("id")]
        if not vector_ids:
            return []

        result = await self.db.execute(
            select(KnowledgeAssetChunk, KnowledgeAsset)
            .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetChunk.asset_id)
            .where(KnowledgeAssetChunk.pinecone_vector_id.in_(vector_ids))
        )

        chunk_rows = {chunk.pinecone_vector_id: (chunk, asset) for chunk, asset in result.all()}
        sources: list[dict[str, Any]] = []
        for match in matches:
            vector_id = match.get("id")
            if vector_id not in chunk_rows:
                continue

            chunk, asset = chunk_rows[vector_id]
            metadata = match.get("metadata") or {}
            sources.append(
                {
                    "asset_id": asset.id,
                    "asset_title": metadata.get("asset_title") or asset.title,
                    "chunk_index": metadata.get("chunk_index") if metadata.get("chunk_index") is not None else chunk.chunk_index,
                    "score": float(match.get("score") or 0.0),
                    "content": chunk.content,
                    "source_url": metadata.get("source_url") or asset.source_url or asset.file_url,
                }
            )

        return sources[: max(limit, 1)]

    async def answer_query(self, team_id: UUID, query: str, limit: int = 5) -> dict[str, Any]:
        sources = await self.search(team_id, query, limit=limit)
        if not sources:
            return {
                "answer": "I couldn't find any indexed knowledge base content that matches that question.",
                "sources": [],
            }

        context_blocks = []
        for index, source in enumerate(sources, start=1):
            context_blocks.append(
                f"Source {index} | {source['asset_title']} | chunk {source['chunk_index']} | score {source['score']:.3f}\n{source['content']}"
            )

        grounded_context = "\n\n".join(context_blocks)

        if settings.grok_api_key:
            prompt = f"""You answer only from the supplied knowledge base context.

Question:
{query}

Knowledge base context:
{grounded_context}

Instructions:
- Answer concisely and directly.
- If the context does not contain the answer, say so.
- Cite sources inline using [1], [2], etc.
"""

            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You are a grounded sales knowledge base assistant."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 900,
            }

            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.grok_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"].strip()
        else:
            answer = "\n\n".join(
                [
                    f"- {source['asset_title']}: {source['content'][:450].strip()}"
                    for source in sources
                ]
            )

        return {
            "answer": answer,
            "sources": sources,
        }