"""
Tests for the ClewAPIClient.

Verifies that the client properly manages HTTP connections,
configuration, and request execution.
"""

from unittest.mock import AsyncMock

import httpx
import pytest

from clew.mcp.client import ClewAPIClient


@pytest.mark.asyncio
async def test_client_context_manager():
    """Test that client can be used as async context manager."""
    async with ClewAPIClient(base_url="http://test", timeout=10) as client:
        assert client._client is not None
        assert isinstance(client._client, httpx.AsyncClient)

    # After exit, client should be closed
    assert client._client is None


@pytest.mark.asyncio
async def test_client_configuration_from_env(monkeypatch):
    """Test that client picks up configuration from environment."""
    monkeypatch.setenv("CONTEXT_ENGINE_API_URL", "http://custom-api:9000")
    monkeypatch.setenv("CLEW_API_KEY", "test-key-123")
    monkeypatch.setenv("CLEW_API_TIMEOUT", "45.5")

    client = ClewAPIClient()

    assert client.base_url == "http://custom-api:9000"
    assert client.api_key == "test-key-123"
    assert client.timeout == 45.5
    assert client.headers["Authorization"] == "Bearer test-key-123"


@pytest.mark.asyncio
async def test_client_search(monkeypatch):
    """Test search method."""
    from unittest.mock import Mock

    # Mock the httpx response (not async)
    mock_response = Mock()
    mock_response.json.return_value = [{"id": "1", "content": "test", "score": 0.9, "metadata": {}}]
    mock_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    async with ClewAPIClient(base_url="http://test") as client:
        client._client = mock_client

        results = await client.search("test query", limit=5, repo_id="myrepo")

        # Verify API was called correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/v1/search/"
        assert call_args[1]["json"]["query"] == "test query"
        assert call_args[1]["json"]["limit"] == 5
        assert call_args[1]["json"]["repo_id"] == "myrepo"

        # Verify results
        assert len(results) == 1
        assert results[0]["id"] == "1"


@pytest.mark.asyncio
async def test_client_traverse(monkeypatch):
    """Test traverse method."""
    from unittest.mock import Mock

    mock_response = Mock()
    mock_response.json.return_value = {
        "nodes": [{"id": "node1"}],
        "edges": [{"source": "node1", "target": "node2", "type": "IMPORTS"}],
    }
    mock_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    async with ClewAPIClient(base_url="http://test") as client:
        client._client = mock_client

        graph = await client.traverse("start_id", relationship_types=["IMPORTS", "CALLS"], depth=3)

        # Verify API was called
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/v1/graph/traverse"
        assert call_args[1]["json"]["start_node_id"] == "start_id"
        assert "IMPORTS" in call_args[1]["json"]["relationship_types"]

        # Verify results
        assert "nodes" in graph
        assert "edges" in graph


@pytest.mark.asyncio
async def test_client_raises_without_context():
    """Test that accessing client property outside context raises error."""
    client = ClewAPIClient()

    with pytest.raises(RuntimeError, match="must be used as async context manager"):
        _ = client.client


@pytest.mark.asyncio
async def test_client_invalid_timeout_env(monkeypatch, caplog):
    """Test that invalid timeout env var falls back to default."""
    monkeypatch.setenv("CLEW_API_TIMEOUT", "not-a-number")

    client = ClewAPIClient()

    assert client.timeout == 30.0  # Default
    assert "Invalid CLEW_API_TIMEOUT" in caplog.text
