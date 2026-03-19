"""Tests for embedding providers (OpenAI and Ollama)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# OpenAI Embedding Tests
# ---------------------------------------------------------------------------


class TestOpenAIEmbeddings:
    @pytest.fixture
    def provider(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            from clewso_ingestion.embeddings import OpenAIEmbeddings

            return OpenAIEmbeddings(api_key="test-key")

    @pytest.mark.asyncio
    async def test_embed_uses_async_client(self, provider):
        """embed() should use AsyncOpenAI and await the response."""
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 1536

        mock_response = MagicMock()
        mock_response.data = [mock_embedding]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client) as mock_cls:
            result = await provider.embed("hello world")

            mock_cls.assert_called_once_with(api_key="test-key")
            mock_client.embeddings.create.assert_awaited_once_with(
                input="hello world", model="text-embedding-3-large", dimensions=1536
            )
            assert result == [0.1] * 1536

    @pytest.mark.asyncio
    async def test_embed_batch_single_api_call(self, provider):
        """embed_batch() should make exactly 1 API call with all texts."""
        texts = ["hello", "world", "foo"]

        mock_embeddings = []
        for _i in range(3):
            m = MagicMock()
            m.embedding = [0.1] * 1536
            mock_embeddings.append(m)

        mock_response = MagicMock()
        mock_response.data = mock_embeddings

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            results = await provider.embed_batch(texts)

            # Exactly 1 API call
            mock_client.embeddings.create.assert_awaited_once_with(
                input=texts, model="text-embedding-3-large", dimensions=1536
            )
            assert len(results) == 3
            assert all(len(e) == 1536 for e in results)

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self, provider):
        """embed_batch([]) should return [] without calling the API."""
        result = await provider.embed_batch([])
        assert result == []


# ---------------------------------------------------------------------------
# Ollama Embedding Tests
# ---------------------------------------------------------------------------


class TestOllamaEmbeddings:
    @pytest.fixture
    def provider(self):
        from clewso_ingestion.embeddings import OllamaEmbeddings

        return OllamaEmbeddings(base_url="http://localhost:11434", model="nomic-embed-text")

    @pytest.mark.asyncio
    async def test_embed_uses_shared_client(self, provider):
        """embed() should use the shared httpx client, not create a new one."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.2] * 1536}

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed("test text")

        provider._client.post.assert_awaited_once()
        assert result == [0.2] * 1536

    @pytest.mark.asyncio
    async def test_embed_batch_concurrency(self, provider):
        """embed_batch() should fan out calls and return results in order."""
        texts = ["a", "b", "c", "d"]

        call_count = 0

        async def mock_embed(text):
            nonlocal call_count
            call_count += 1
            return [float(ord(text))] * 1536

        provider.embed = mock_embed

        results = await provider.embed_batch(texts)

        assert call_count == 4
        assert len(results) == 4
        # Results should be in the same order as input
        assert results[0][0] == float(ord("a"))
        assert results[3][0] == float(ord("d"))

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self, provider):
        """embed_batch([]) should return [] without any calls."""
        result = await provider.embed_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_close(self, provider):
        """close() should call aclose() on the shared client."""
        provider._client = AsyncMock()
        provider._client.aclose = AsyncMock()

        await provider.close()

        provider._client.aclose.assert_awaited_once()
