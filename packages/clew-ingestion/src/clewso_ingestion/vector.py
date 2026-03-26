import asyncio
import logging
import os
import uuid
from typing import Any, Protocol

from qdrant_client import QdrantClient
from qdrant_client.http import models
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_NO_PROVIDER_MSG = "No embedding provider configured. Initialize VectorStore with an embedding provider."


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed texts."""
        ...


def _repo_file_filter(repo_id: str, file_path: str) -> models.Filter:
    """Build a Qdrant filter matching a repo + file path."""
    return models.Filter(
        must=[
            models.FieldCondition(key="repo_id", match=models.MatchValue(value=repo_id)),
            models.FieldCondition(key="path", match=models.MatchValue(value=file_path)),
        ]
    )


class VectorStore:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        url: str | None = None,
        api_key: str | None = None,
        host: str | None = None,
        port: int | None = None,
        collection: str | None = None,
    ):
        # Explicit params → env vars → defaults
        url = url or os.getenv("QDRANT_API_ENDPOINT") or os.getenv("QDRANT_URL") or ""
        api_key = api_key or os.getenv("QDRANT_API_TOKEN") or os.getenv("QDRANT_API_KEY") or ""
        if url:
            self.client = QdrantClient(url=url, api_key=api_key or None)
        else:
            host = host or os.getenv("QDRANT_HOST", "localhost")
            port = port or int(os.getenv("QDRANT_PORT", "6335"))
            self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection or "codebase"
        self.embedding_provider = embedding_provider
        self._ensure_collection()
        self._buffer: list[models.PointStruct] = []
        self._batch_size = 50

    def _ensure_collection(self):
        try:
            self.client.get_collection(self.collection_name)
        except Exception:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),
            )
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self):
        """Create payload indexes required for filtered queries."""
        for field_name in ("repo_id", "path", "type"):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass  # Already exists

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _upsert_with_retry(self, points: list[models.PointStruct]) -> None:
        """Upsert points to Qdrant with retry on transient failures."""
        self.client.upsert(collection_name=self.collection_name, points=points)

    def _require_provider(self) -> EmbeddingProvider:
        if not self.embedding_provider:
            raise RuntimeError(_NO_PROVIDER_MSG)
        return self.embedding_provider

    async def _auto_flush(self) -> None:
        """Flush the buffer when it exceeds ``_batch_size``."""
        if len(self._buffer) >= self._batch_size:
            await self.flush()

    # -- write operations --------------------------------------------------

    async def add(self, text: str, metadata: dict[str, Any]) -> str:
        """Add a text entry to the vector store."""
        provider = self._require_provider()
        try:
            embedding = await provider.embed(text)
        except Exception as exc:
            logger.error("Failed to generate embedding for %s: %s", metadata.get("path", "unknown"), exc)
            raise

        point_id = str(uuid.uuid4())
        self._buffer.append(models.PointStruct(id=point_id, vector=embedding, payload={"text": text, **metadata}))
        await self._auto_flush()
        return point_id

    async def flush(self):
        if not self._buffer:
            return
        batch = self._buffer
        self._buffer = []
        await asyncio.to_thread(self._upsert_with_retry, batch)

    async def add_batch(
        self,
        items: list[tuple[str, dict[str, Any], str | None]],
    ) -> list[str]:
        """Add multiple text entries in one batch.

        Embeds all texts, then upserts the resulting points directly
        (bypassing the internal buffer).  This is safe for concurrent
        callers — each call owns its own points list.
        """
        if not items:
            return []

        provider = self._require_provider()
        texts = [text for text, _, _ in items]

        try:
            embeddings = await provider.embed_batch(texts)
        except Exception as exc:
            logger.error("Failed to generate batch embeddings: %s", exc)
            raise

        points: list[models.PointStruct] = []
        point_ids: list[str] = []
        for (text, metadata, optional_id), embedding in zip(items, embeddings, strict=True):
            point_id = optional_id or str(uuid.uuid4())
            point_ids.append(point_id)
            points.append(models.PointStruct(id=point_id, vector=embedding, payload={"text": text, **metadata}))

        await asyncio.to_thread(self._upsert_with_retry, points)
        return point_ids

    async def upsert(self, text: str, metadata: dict[str, Any]) -> str:
        point_id = await self.add(text, metadata)
        await self.flush()
        return point_id

    # -- delete operations -------------------------------------------------

    async def delete(self, id: str) -> None:
        """Delete a single vector by its deterministic ID."""
        self._delete_points([id])

    def _delete_points(self, point_ids: list) -> None:
        """Delete points by their IDs (no-op for empty list)."""
        if point_ids:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=point_ids),
            )

    def _scroll_file_points(self, repo_id: str, file_path: str) -> list:
        """Return point IDs matching a repo + file path."""
        results, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=_repo_file_filter(repo_id, file_path),
            limit=1000,
        )
        return [r.id for r in results]

    def delete_by_filter(self, repo_id: str, file_path: str) -> int:
        """Delete vectors matching repo_id and file path (best-effort)."""
        try:
            point_ids = self._scroll_file_points(repo_id, file_path)
            self._delete_points(point_ids)
            return len(point_ids)
        except Exception as exc:
            logger.warning("Failed to delete vectors for %s: %s", file_path, exc)
            return 0

    def delete_files_batch(self, repo_id: str, file_paths: list[str]) -> int:
        """Delete vectors for multiple files in a single bulk call."""
        if not file_paths:
            return 0
        try:
            all_ids: list[str] = []
            for fp in file_paths:
                all_ids.extend(self._scroll_file_points(repo_id, fp))
            self._delete_points(all_ids)
            return len(all_ids)
        except Exception as exc:
            logger.warning("Failed to batch delete vectors: %s", exc)
            return 0


# Protocol conformance check
def _check_vector_writer_protocol() -> None:
    from clewso_core.protocols import VectorWriter

    assert isinstance(VectorStore(embedding_provider=None), VectorWriter)  # type: ignore[abstract]
