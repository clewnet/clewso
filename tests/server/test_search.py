"""
Tests for the /v1/search endpoint.
"""

import pytest


@pytest.mark.asyncio
async def test_search_returns_results(client, mock_vector_store):
    """Search endpoint returns scored results from vector store."""
    resp = await client.post("/v1/search/", json={"query": "authentication"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["id"] == "file:src/auth.py"
    assert data[0]["score"] == 0.92
    assert data[0]["metadata"]["path"] == "src/auth.py"


@pytest.mark.asyncio
async def test_search_passes_limit(client, mock_vector_store):
    """Limit parameter is forwarded to vector store."""
    await client.post("/v1/search/", json={"query": "auth", "limit": 3, "exclude_tests": False, "graph_boost": False})

    call_kwargs = mock_vector_store.search.call_args.kwargs
    assert call_kwargs["limit"] == 3


@pytest.mark.asyncio
async def test_search_passes_repo_filter(client, mock_vector_store):
    """Repo filter is forwarded to vector store."""
    await client.post("/v1/search/", json={"query": "auth", "repo": "owner/my-repo"})

    call_kwargs = mock_vector_store.search.call_args.kwargs
    assert call_kwargs["repo"] == "owner/my-repo"


@pytest.mark.asyncio
async def test_search_passes_filters(client, mock_vector_store):
    """Extra filters dict is forwarded to vector store."""
    filters = {"path_contains": "src/"}
    await client.post("/v1/search/", json={"query": "auth", "filters": filters})

    call_kwargs = mock_vector_store.search.call_args.kwargs
    assert call_kwargs["filters"] == filters


@pytest.mark.asyncio
async def test_search_empty_results(client, mock_vector_store):
    """Empty result set returns an empty list, not an error."""
    mock_vector_store.search.return_value = []

    resp = await client.post("/v1/search/", json={"query": "nonexistent"})

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_search_calls_embeddings(client, mock_embeddings):
    """Search endpoint calls embed() with the query text."""
    await client.post("/v1/search/", json={"query": "session validation"})

    mock_embeddings.embed.assert_awaited_once_with("session validation")


@pytest.mark.asyncio
async def test_search_embedding_failure_uses_fallback(client, mock_embeddings, mock_vector_store):
    """When embedding provider fails, search falls back to hash vectors."""
    mock_embeddings.embed.side_effect = RuntimeError("API key invalid")

    resp = await client.post("/v1/search/", json={"query": "anything"})

    # Should still succeed — fallback produces a vector and search proceeds
    assert resp.status_code == 200
    # Vector store should have been called with a 1536-dim fallback vector
    call_kwargs = mock_vector_store.search.call_args.kwargs
    assert len(call_kwargs["query_vector"]) == 1536


@pytest.mark.asyncio
async def test_search_validation_rejects_missing_query(client):
    """Request without 'query' field returns 422."""
    resp = await client.post("/v1/search/", json={"limit": 5})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_with_reranking(client, test_app, mock_vector_store, mock_embeddings):
    """Search with rerank=True calls the reranker and re-sorts results."""
    from unittest.mock import AsyncMock

    from clew.server.dependencies import get_reranker

    # 1. Setup mock reranker
    mock_reranker = AsyncMock()
    # Return scores that reverse the order: [0.1, 0.9]
    mock_reranker.rerank.return_value = [0.1, 0.9]

    # 2. Inject the mock
    test_app.dependency_overrides[get_reranker] = lambda: mock_reranker

    try:
        # 3. Request search with reranking
        resp = await client.post("/v1/search/", json={"query": "auth", "rerank": True})

        assert resp.status_code == 200
        data = resp.json()

        # Original order from mock_vector_store (mocked in conftest):
        # 1. src/auth.py (score 0.92)
        # 2. tests/test_auth.py (score 0.85)

        # After reranking with scores [0.1, 0.9], the order should flip
        assert len(data) == 2
        # The second item (src/middleware.py) should now be first because it got a 0.9 rerank score
        assert data[0]["score"] == 0.9
        assert data[0]["id"] == "file:src/middleware.py"

        mock_reranker.rerank.assert_awaited_once()
    finally:
        # Cleanup
        test_app.dependency_overrides.clear()
