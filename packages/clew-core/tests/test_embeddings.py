"""Tests for shared clew-core embeddings module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from clewso_core.embeddings import (
    HashEmbeddings,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    get_embedding_provider,
)

# ---------------------------------------------------------------------------
# OpenAIEmbeddings
# ---------------------------------------------------------------------------


class TestOpenAIEmbeddings:
    def test_raises_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            with pytest.raises(ValueError, match="OPENAI_API_KEY not set"):
                OpenAIEmbeddings()

    @pytest.mark.asyncio
    async def test_embed(self):
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

        with patch("openai.AsyncOpenAI") as mock_cls:
            client = AsyncMock()
            mock_cls.return_value = client
            client.embeddings.create = AsyncMock(return_value=mock_response)

            provider = OpenAIEmbeddings(api_key="test-key", model="test-model", dimensions=3)
            result = await provider.embed("hello")

        assert result == [0.1, 0.2, 0.3]
        client.embeddings.create.assert_awaited_once_with(input="hello", model="test-model", dimensions=3)

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        embeddings_data = [[float(i)] for i in range(5)]
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=e) for e in embeddings_data]

        with patch("openai.AsyncOpenAI") as mock_cls:
            client = AsyncMock()
            mock_cls.return_value = client
            client.embeddings.create = AsyncMock(return_value=mock_response)

            provider = OpenAIEmbeddings(api_key="test-key", dimensions=1)
            texts = [f"text {i}" for i in range(5)]
            result = await provider.embed_batch(texts)

        assert result == embeddings_data

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self):
        provider = OpenAIEmbeddings(api_key="test-key")
        assert await provider.embed_batch([]) == []

    def test_dimension_property(self):
        provider = OpenAIEmbeddings(api_key="test-key", dimensions=1024)
        assert provider.dimension == 1024


# ---------------------------------------------------------------------------
# OllamaEmbeddings
# ---------------------------------------------------------------------------


class TestOllamaEmbeddings:
    @pytest.mark.asyncio
    async def test_embed_success(self):
        provider = OllamaEmbeddings(base_url="http://localhost:11434", model="nomic-embed-text")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.5, 0.6]}

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed("test text")
        assert result == [0.5, 0.6]

    @pytest.mark.asyncio
    async def test_embed_api_error(self):
        provider = OllamaEmbeddings()

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(ValueError, match="Ollama API error: 503"):
            await provider.embed("test")

    @pytest.mark.asyncio
    async def test_embed_network_error(self):
        provider = OllamaEmbeddings()
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(side_effect=httpx.RequestError("conn refused", request=MagicMock()))

        with pytest.raises(httpx.RequestError):
            await provider.embed("test")

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self):
        provider = OllamaEmbeddings()
        assert await provider.embed_batch([]) == []

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        provider = OllamaEmbeddings()
        provider._client = AsyncMock()

        call_count = 0

        async def _fake_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"embedding": [float(call_count)]}
            return m

        provider._client.post = _fake_post

        result = await provider.embed_batch(["a", "b", "c"])
        assert len(result) == 3
        assert call_count == 3


# ---------------------------------------------------------------------------
# HashEmbeddings
# ---------------------------------------------------------------------------


class TestHashEmbeddings:
    @pytest.mark.asyncio
    async def test_embed_deterministic(self):
        provider = HashEmbeddings(dimension=4)
        r1 = await provider.embed("hello")
        r2 = await provider.embed("hello")
        assert r1 == r2
        assert len(r1) == 4

    @pytest.mark.asyncio
    async def test_embed_different_texts(self):
        provider = HashEmbeddings(dimension=4)
        r1 = await provider.embed("hello")
        r2 = await provider.embed("world")
        assert r1 != r2

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        provider = HashEmbeddings(dimension=8)
        results = await provider.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        for r in results:
            assert len(r) == 8


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestGetEmbeddingProvider:
    def test_returns_openai_when_key_set(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        provider = get_embedding_provider()
        assert isinstance(provider, OpenAIEmbeddings)

    def test_returns_ollama_when_url_set(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
        provider = get_embedding_provider()
        assert isinstance(provider, OllamaEmbeddings)

    def test_returns_hash_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        provider = get_embedding_provider()
        assert isinstance(provider, HashEmbeddings)
