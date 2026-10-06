from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService


async def test_knowledge_search_is_optional_without_pinecone():
    database = AsyncMock()
    service = KnowledgeBaseRAGService(database)

    with (
        patch("app.services.knowledge_base_rag_service.settings.pinecone_api_key", ""),
        patch("app.services.knowledge_base_rag_service.settings.pinecone_index_name", ""),
        patch.object(service, "_pinecone_query", new_callable=AsyncMock) as query,
    ):
        results = await service.search(uuid4(), "hello")

    assert results == []
    query.assert_not_awaited()
    database.execute.assert_not_awaited()


async def test_empty_knowledge_query_does_not_require_pinecone():
    database = AsyncMock()
    service = KnowledgeBaseRAGService(database)

    with patch.object(service, "_pinecone_query", new_callable=AsyncMock) as query:
        results = await service.search(uuid4(), "   ")

    assert results == []
    query.assert_not_awaited()
