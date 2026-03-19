import logging
import os
import uuid
from typing import Any, Protocol

from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed texts."""
        ...


class VectorStore:
    def __init__(self, embedding_provider: EmbeddingProvider | None = None):
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", 6335))
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = "codebase"
        self.embedding_provider = embedding_provider
        self._ensure_collection()
        self._buffer: list[models.PointStruct] = []
        self._batch_size = 100

    def _ensure_collection(self):
        try:
            self.client.get_collection(self.collection_name)
        except Exception:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),
            )

    async def add(self, text: str, metadata: dict[str, Any]) -> str:
        """
        Add a text entry to the vector store.

        Args:
            text: Text content to embed and index
            metadata: Additional metadata (path, repo_id, etc.)

        Returns:
            Generated point ID
        """
        if not self.embedding_provider:
            raise RuntimeError("No embedding provider configured. Initialize VectorStore with an embedding provider.")

        # Generate real embedding
        try:
            # Run async embed in sync context
            embedding = await self.embedding_provider.embed(text)
        except Exception as e:
            logger.error(f"Failed to generate embedding for {metadata.get('path', 'unknown')}: {e}")
            raise

        point_id = str(uuid.uuid4())

        self._buffer.append(models.PointStruct(id=point_id, vector=embedding, payload={"text": text, **metadata}))

        if len(self._buffer) >= self._batch_size:
            await self.flush()

        return point_id

    async def flush(self):
        if not self._buffer:
            return

        self.client.upsert(
            collection_name=self.collection_name,
            points=self._buffer,
        )
        self._buffer = []

    async def add_batch(
        self,
        items: list[tuple[str, dict[str, Any], str | None]],
    ) -> list[str]:
        """
        Add multiple text entries to the vector store in one batch.

        Calls embed_batch() once for all texts, then buffers
        the resulting points. Flushes when the buffer exceeds _batch_size.

        Args:
            items: List of (text, metadata, optional_id) tuples.


        Returns:
            List of point IDs used/generated, one per item.
        """
        if not items:
            return []

        if not self.embedding_provider:
            raise RuntimeError("No embedding provider configured. Initialize VectorStore with an embedding provider.")

        texts = [text for text, _, _ in items]

        try:
            embeddings = await self.embedding_provider.embed_batch(texts)
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            raise

        point_ids: list[str] = []
        for (text, metadata, optional_id), embedding in zip(items, embeddings, strict=True):
            point_id = optional_id or str(uuid.uuid4())

            point_ids.append(point_id)
            self._buffer.append(
                models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={"text": text, **metadata},
                )
            )

        if len(self._buffer) >= self._batch_size:
            await self.flush()

        return point_ids

    async def upsert(self, text: str, metadata: dict[str, Any]) -> str:
        point_id = await self.add(text, metadata)
        await self.flush()
        return point_id

    async def delete(self, id: str) -> None:
        """Delete a single vector by its deterministic ID.

        Args:
            id: The point ID to delete (typically a sha256 hex string).
        """
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=[id]),
        )

    def delete_by_filter(self, repo_id: str, file_path: str) -> int:
        """
        Delete vectors matching repo_id and file path.

        Uses metadata filtering to find and delete vectors associated
        with a specific file in a repository.

        Args:
            repo_id: Repository identifier
            file_path: Path to the file whose vectors should be deleted

        Returns:
            Number of vectors deleted
        """
        try:
            # Search for matching points using metadata filter
            results, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(key="repo_id", match=models.MatchValue(value=repo_id)),
                        models.FieldCondition(key="path", match=models.MatchValue(value=file_path)),
                    ]
                ),
                limit=1000,  # Should be enough for one file
            )

            # Extract point IDs
            point_ids = [r.id for r in results]

            # Delete by IDs
            if point_ids:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.PointIdsList(points=point_ids),
                )

            return len(point_ids)

        except Exception as e:
            # Log but don't fail - deletion is best-effort
            import logging

            logging.getLogger(__name__).warning(f"Failed to delete vectors for {file_path}: {e}")
            return 0

    def delete_files_batch(self, repo_id: str, file_paths: list[str]) -> int:
        """
        Delete vectors for multiple files in a batch.

        More efficient than calling delete_by_filter() in a loop.

        Args:
            repo_id: Repository identifier
            file_paths: List of file paths to delete

        Returns:
            Total number of vectors deleted
        """
        if not file_paths:
            return 0

        total_deleted = 0

        try:
            # For each file path, collect point IDs
            all_point_ids = []

            for file_path in file_paths:
                results, _ = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(key="repo_id", match=models.MatchValue(value=repo_id)),
                            models.FieldCondition(key="path", match=models.MatchValue(value=file_path)),
                        ]
                    ),
                    limit=1000,
                )

                all_point_ids.extend([r.id for r in results])

            # Delete all points in one call
            if all_point_ids:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.PointIdsList(points=all_point_ids),
                )
                total_deleted = len(all_point_ids)

        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"Failed to batch delete vectors: {e}")

        return total_deleted
