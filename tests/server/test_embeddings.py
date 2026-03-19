from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from clew.server.adapters.embeddings import OllamaEmbeddings

# ---------------------------------------------------------------------------
# OllamaEmbeddings tests
# The new implementation (from clew-core) uses a persistent _client rather
# than an `async with httpx.AsyncClient()` per call. Tests stub _client directly.
# ---------------------------------------------------------------------------


@pytest.fixture
def provider():
    return OllamaEmbeddings(base_url="http://localhost:11434", model="nomic-embed-text")


@pytest.mark.asyncio
async def test_ollama_embeddings_success(provider):
    """Test successful embedding generation."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embedding": [0.1, 0.2]}

    provider._client = AsyncMock()
    provider._client.post = AsyncMock(return_value=mock_response)

    result = await provider.embed("test")
    assert result == [0.1, 0.2]
    provider._client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_ollama_embeddings_network_error(provider):
    """Test network error handling."""
    provider._client = AsyncMock()
    provider._client.post = AsyncMock(side_effect=httpx.RequestError("Network error", request=MagicMock()))

    with pytest.raises(httpx.RequestError):
        await provider.embed("test")


@pytest.mark.asyncio
async def test_ollama_embeddings_api_error(provider):
    """Test API error (non-200 status)."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    provider._client = AsyncMock()
    provider._client.post = AsyncMock(return_value=mock_response)

    with pytest.raises(ValueError, match="Ollama API error: 500"):
        await provider.embed("test")


@pytest.mark.asyncio
async def test_ollama_embeddings_json_key_error(provider):
    """Test missing 'embedding' key in response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}

    provider._client = AsyncMock()
    provider._client.post = AsyncMock(return_value=mock_response)

    with pytest.raises(KeyError):
        await provider.embed("test")


@pytest.mark.asyncio
async def test_ollama_embeddings_unexpected_error(provider):
    """Test unexpected error propagation."""
    provider._client = AsyncMock()
    provider._client.post = AsyncMock(side_effect=TypeError("Unexpected error"))

    with pytest.raises(TypeError, match="Unexpected error"):
        await provider.embed("test")
