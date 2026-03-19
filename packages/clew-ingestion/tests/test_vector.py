import uuid
from unittest.mock import patch

import pytest


# Mock embedding provider for testing
class MockEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 1536


class TestVectorStore:
    @pytest.fixture
    def vector_store_setup(self):
        # Patch QdrantClient WHERE IT IS USED in src.vector
        with patch("clewso_ingestion.vector.QdrantClient") as MockClientClass:
            # Import locally to ensure we get the currently-patched/loaded module
            from clewso_ingestion.vector import VectorStore

            mock_embeddings = MockEmbeddingProvider()
            store = VectorStore(embedding_provider=mock_embeddings)

            # Replace the client with the one from the mock class
            mock_client_instance = MockClientClass.return_value
            store.client = mock_client_instance

            yield store, MockClientClass, mock_client_instance

    def test_init(self, vector_store_setup):
        """Test initialization and collection check."""
        store, mock_client_class, mock_client_instance = vector_store_setup
        mock_client_class.assert_called_once()
        mock_client_instance.get_collection.assert_called_once_with("codebase")

    def test_ensure_collection_missing(self, vector_store_setup):
        """Test collection creation if it doesn't exist."""
        store, _, mock_client_instance = vector_store_setup

        # Reset mocks from setUp
        mock_client_instance.get_collection.reset_mock()
        mock_client_instance.get_collection.side_effect = Exception("Collection not found")

        # Re-run the check
        store._ensure_collection()

        mock_client_instance.get_collection.assert_called_once()
        mock_client_instance.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert(self, vector_store_setup):
        """Test the full upsert flow (add + flush)."""
        store, _, mock_client_instance = vector_store_setup
        text = "sample code"
        metadata = {"file": "test.py"}

        # Now async
        point_id = await store.upsert(text, metadata)

        # Verify UUID was generated
        assert isinstance(uuid.UUID(point_id), uuid.UUID)

        # Verify Qdrant upsert was called
        mock_client_instance.upsert.assert_called_once()
        call_args = mock_client_instance.upsert.call_args
        assert call_args.kwargs["collection_name"] == "codebase"
        assert len(call_args.kwargs["points"]) == 1
        assert call_args.kwargs["points"][0].payload["text"] == text

    @pytest.mark.asyncio
    async def test_flush_empty(self, vector_store_setup):
        """Flush should do nothing if buffer is empty."""
        store, _, mock_client_instance = vector_store_setup
        mock_client_instance.upsert.reset_mock()

        # Now async
        await store.flush()

        mock_client_instance.upsert.assert_not_called()
