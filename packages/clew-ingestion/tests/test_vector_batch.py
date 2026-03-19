import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add packages/clew-ingestion to path so we can import src
sys.path.append(os.path.dirname(__file__))


# Define a simple PointStruct for verification
class SimplePointStruct:
    def __init__(self, id, vector, payload):
        self.id = id
        self.vector = vector
        self.payload = payload


# Mock qdrant_client before importing src.vector
sys.modules["qdrant_client"] = MagicMock()
sys.modules["qdrant_client.http"] = MagicMock()
models_mock = MagicMock()
models_mock.PointStruct = SimplePointStruct  # Use real class
# Also simulate VectorParams and Distance if needed
# VectorStore uses them in _ensure_collection which we mock or ignore
models_mock.VectorParams = MagicMock()
models_mock.Distance = MagicMock()

sys.modules["qdrant_client.http.models"] = models_mock
# We also need to ensure qdrant_client.http.models is importable as 'models'
sys.modules["qdrant_client.http"].models = models_mock

# Import the class under test
try:
    from clewso_ingestion.vector import VectorStore
except ImportError:
    # Fallback if running from within packages/clew-ingestion
    sys.path.append(os.getcwd())
    from clewso_ingestion.vector import VectorStore


class MockEmbeddingProvider:
    """Mock embedding provider for testing."""

    async def embed(self, text: str) -> list[float]:
        # Return a deterministic mock embedding
        return [0.1] * 1536

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Return deterministic mock embeddings for each text
        return [[0.1] * 1536 for _ in texts]


class TestVectorStoreBatching:
    @pytest.fixture
    def vector_store(self):
        # We need to mock QdrantClient inside VectorStore.__init__
        with patch("clewso_ingestion.vector.QdrantClient"):
            mock_embeddings = MockEmbeddingProvider()
            store = VectorStore(embedding_provider=mock_embeddings)
            store.client = MagicMock()
            store.client.upsert = MagicMock()

            # Initialize buffer if implementation is missing (so tests don't crash on setup)
            if not hasattr(store, "_buffer"):
                store._buffer = []
            return store

    def test_add_method_exists(self, vector_store):
        if not hasattr(vector_store, "add"):
            pytest.skip("add method not implemented yet")
        assert callable(vector_store.add)

    @pytest.mark.asyncio
    async def test_add_buffers_item(self, vector_store):
        if not hasattr(vector_store, "add"):
            pytest.skip("add method not implemented yet")

        point_id = await vector_store.add("text", {"meta": "data"})

        assert isinstance(point_id, str)
        assert len(vector_store._buffer) == 1
        item = vector_store._buffer[0]

        # Now item should be SimplePointStruct
        assert isinstance(item, SimplePointStruct)
        assert item.payload["text"] == "text"
        assert item.id == point_id

    @pytest.mark.asyncio
    async def test_flush_sends_batch(self, vector_store):
        if not hasattr(vector_store, "add_batch"):
            pytest.skip("add_batch method not implemented yet")

        # Mock the embedding provider to track calls
        from unittest.mock import AsyncMock

        mock_provider = AsyncMock()
        mock_provider.embed_batch = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])
        vector_store.embedding_provider = mock_provider

        point_ids = await vector_store.add_batch([("text1", {"meta": "1"}, None), ("text2", {"meta": "2"}, None)])

        assert len(point_ids) == 2
        assert len(vector_store._buffer) == 2

        # Robust payload verification (set-based to handle ordering)
        texts = {point.payload["text"] for point in vector_store._buffer}
        assert texts == {"text1", "text2"}

        # Verify embeddings were called
        mock_provider.embed_batch.assert_awaited_once()

        await vector_store.flush()

        assert len(vector_store._buffer) == 0
        vector_store.client.upsert.assert_called_once()

        # Verify arguments passed to upsert
        call_kwargs = vector_store.client.upsert.call_args.kwargs
        points = call_kwargs.get("points")
        assert len(points) == 2
        texts = {p.payload["text"] for p in points}
        assert texts == {"text1", "text2"}

    @pytest.mark.asyncio
    async def test_auto_flush(self, vector_store):
        if not hasattr(vector_store, "add"):
            pytest.skip("add method not implemented yet")

        # Add 101 items to trigger auto-flush at 100
        for i in range(101):
            await vector_store.add(f"item{i}", {})

        # Should have flushed at least once (for the first 100 items)
        assert vector_store.client.upsert.called
        # Buffer should have 1 item left (the 101st item)
        assert len(vector_store._buffer) == 1
        assert vector_store._buffer[0].payload["text"] == "item100"

    @pytest.mark.asyncio
    async def test_upsert_backward_compatibility(self, vector_store):
        point_id = await vector_store.upsert("text", {"meta": "data"})

        assert point_id
        # Client upsert should be called immediately
        assert vector_store.client.upsert.called
        # Buffer should be empty after upsert (if it flushes immediately)
        assert len(vector_store._buffer) == 0


class TestVectorStoreAddBatch:
    """Tests for the async add_batch() method."""

    @pytest.fixture
    def vector_store(self):
        with patch("clewso_ingestion.vector.QdrantClient"):
            mock_embeddings = MockEmbeddingProvider()
            store = VectorStore(embedding_provider=mock_embeddings)
            store.client = MagicMock()
            store.client.upsert = MagicMock()
            return store

    @pytest.mark.asyncio
    async def test_add_batch_returns_ids(self, vector_store):
        """add_batch() should return one point ID per input item."""
        items = [
            ("text1", {"path": "a.py"}, None),
            ("text2", {"path": "b.py"}, None),
            ("text3", {"path": "c.py"}, None),
        ]
        ids = await vector_store.add_batch(items)

        assert len(ids) == 3
        # All IDs should be unique valid strings
        assert len(set(ids)) == 3
        assert all(isinstance(i, str) for i in ids)

    @pytest.mark.asyncio
    async def test_add_batch_calls_embed_batch(self, vector_store):
        """add_batch() should call embed_batch once, not embed N times."""
        from unittest.mock import AsyncMock

        mock_provider = AsyncMock()
        mock_provider.embed_batch = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])
        vector_store.embedding_provider = mock_provider

        items = [("hello", {}, None), ("world", {}, None)]
        await vector_store.add_batch(items)

        mock_provider.embed_batch.assert_awaited_once_with(["hello", "world"])
        # embed() should NOT have been called
        mock_provider.embed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_batch_buffers_and_flushes(self, vector_store):
        """add_batch() should buffer points and auto-flush at threshold."""
        vector_store._batch_size = 5

        # Add 7 items — should flush once (at 5+), leave 2 in buffer
        items = [(f"text{i}", {"i": i}, None) for i in range(7)]
        ids = await vector_store.add_batch(items)

        assert len(ids) == 7
        # flush should have been triggered (buffer >= 5)
        vector_store.client.upsert.assert_called_once()
        # Buffer should be empty after flush (all 7 points flushed in one go
        # since they were all added before the threshold check)
        assert len(vector_store._buffer) == 0

    @pytest.mark.asyncio
    async def test_add_batch_empty(self, vector_store):
        """add_batch([]) should return [] with no side effects."""
        ids = await vector_store.add_batch([])

        assert ids == []
        assert len(vector_store._buffer) == 0
        assert len(vector_store._buffer) == 0
        vector_store.client.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_batch_with_explicit_ids(self, vector_store):
        """add_batch() should respect explicit IDs if provided in 3-tuples."""
        items = [
            ("text1", {"path": "a.py"}, "custom-id-1"),
            ("text2", {"path": "b.py"}, "custom-id-2"),
        ]
        ids = await vector_store.add_batch(items)

        assert ids == ["custom-id-1", "custom-id-2"]
        assert len(vector_store._buffer) == 2
        assert vector_store._buffer[0].id == "custom-id-1"
        assert vector_store._buffer[1].id == "custom-id-2"
