"""
Qdrant Vector Store Adapter

Implements the VectorStore protocol for Qdrant.
"""

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from .base import CodeMetadata, SearchFilters, SearchResult, VectorStore

logger = logging.getLogger("clew.adapters.qdrant")


class QdrantStore:
    """Qdrant implementation of VectorStore protocol."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        url: str = "",
        api_key: str = "",
        collection_name: str = "codebase",
    ):
        self.host = host
        self.port = port
        self.url = url
        self.api_key = api_key
        self.collection_name = collection_name
        self._client: AsyncQdrantClient | None = None

    @property
    def client(self) -> AsyncQdrantClient:
        """Lazy-initialize the Qdrant client."""
        if self._client is None:
            if self.url:
                self._client = AsyncQdrantClient(url=self.url, api_key=self.api_key or None)
            else:
                self._client = AsyncQdrantClient(host=self.host, port=self.port)
        return self._client

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        repo: str | None = None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar vectors in Qdrant.

        Args:
            query_vector: The embedding vector to search with
            limit: Maximum number of results
            repo: Optional repository filter
            filters: Optional additional filters. Supports:
                - path: Exact match on file path
                - path_contains: Substring match on path
                - type: Match on node type (file, function, class, etc)

        Returns:
            List of SearchResult objects
        """
        # Build filter conditions
        must_conditions = []

        if repo:
            must_conditions.append(models.FieldCondition(key="repo_id", match=models.MatchValue(value=repo)))

        # Process additional filters
        if filters:
            # Exact path match
            if "path" in filters:
                must_conditions.append(
                    models.FieldCondition(key="path", match=models.MatchValue(value=filters["path"]))
                )
            # Path contains (substring match using MatchText)
            if "path_contains" in filters:
                must_conditions.append(
                    models.FieldCondition(key="path", match=models.MatchText(text=filters["path_contains"]))
                )
            # Type filter
            if "type" in filters:
                must_conditions.append(
                    models.FieldCondition(key="type", match=models.MatchValue(value=filters["type"]))
                )

        query_filter = models.Filter(must=must_conditions) if must_conditions else None  # type: ignore

        try:
            results_obj = await self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                query_filter=query_filter,
            )
            points = results_obj.points

            return [
                SearchResult(
                    id=str(point.id),
                    score=point.score,
                    content=point.payload.get("text", "") if point.payload else "",
                    metadata=dict(point.payload) if point.payload else {},  # type: ignore[arg-type]
                )
                for point in points
            ]
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}", exc_info=True)
            raise

    async def upsert(self, id: str, content: str, vector: list[float], metadata: CodeMetadata | None = None) -> None:
        """
        Upsert a point into Qdrant.
        """
        try:
            # Qdrant expects UUIDs or integers for point IDs
            # If id is not a valid UUID string, we use it as a key in payload
            # but for the actual point ID we need something compatible.
            # For simplicity, if it's a path, we can hash it to a UUID.
            import hashlib
            import uuid

            try:
                point_id = str(uuid.UUID(id))
            except ValueError:
                point_id = str(uuid.UUID(hashlib.md5(id.encode()).hexdigest()))

            payload = (metadata or {}).copy()
            payload["text"] = content

            await self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=dict(payload),  # type: ignore[arg-type]
                    )
                ],
            )
            logger.debug(f"Qdrant upsert successful for {id}")
        except Exception as e:
            logger.error(f"Qdrant upsert failed: {e}", exc_info=True)
            raise


# Type check: ensure QdrantStore implements VectorStore
def _check_protocol() -> VectorStore:
    return QdrantStore()  # type: ignore


# =============================================================================
# Auto-registration
# =============================================================================


def _register_qdrant():
    """Register Qdrant adapter with the registry."""
    from ..config import settings
    from . import registry

    def factory() -> QdrantStore:
        return QdrantStore(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            collection_name=settings.QDRANT_COLLECTION,
        )

    registry.vector_store_registry.register("qdrant", factory)


# Auto-register on module import
try:
    _register_qdrant()
    logger.debug("Registered Qdrant adapter")
except ImportError as e:
    # Config or registry not available (e.g., during testing), skip registration
    logger.debug(f"Skipping Qdrant auto-registration: {e}")
