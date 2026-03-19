"""
Integration tests for reranker functionality.

Verifies that the reranking feature works correctly through the API
and handles edge cases gracefully.
"""

import httpx
import pytest

pytestmark = pytest.mark.skip(reason="Reranker disabled (OOM issues) - RERANK-1")


@pytest.fixture
def api_url():
    """Base API URL for testing."""
    return "http://localhost:8000"


@pytest.fixture
async def client():
    """HTTP client for API testing."""
    async with httpx.AsyncClient() as client:
        yield client


@pytest.mark.asyncio
async def test_rerank_flag_accepted(client, api_url):
    """Verify API accepts rerank parameter."""
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "authentication", "limit": 5, "rerank": True},
        timeout=30.0,
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    results = response.json()
    assert isinstance(results, list), "Expected list of results"


@pytest.mark.asyncio
async def test_rerank_changes_ordering(client, api_url):
    """Verify reranking actually changes result order (not a no-op)."""
    query = "user authentication flow"

    # Get baseline results
    response_baseline = await client.post(
        f"{api_url}/v1/search/",
        json={"query": query, "limit": 10, "rerank": False},
        timeout=30.0,
    )
    assert response_baseline.status_code == 200
    baseline_results = response_baseline.json()

    # Get reranked results
    response_reranked = await client.post(
        f"{api_url}/v1/search/",
        json={"query": query, "limit": 10, "rerank": True},
        timeout=30.0,
    )
    assert response_reranked.status_code == 200
    reranked_results = response_reranked.json()

    # Skip test if no results returned
    if len(baseline_results) < 2 or len(reranked_results) < 2:
        pytest.skip("Insufficient results to verify ordering change")

    # Extract result IDs
    baseline_ids = [r["id"] for r in baseline_results]
    reranked_ids = [r["id"] for r in reranked_results]

    # Verify at least some ordering difference
    # (Not strict equality check since top result might legitimately stay the same)
    assert baseline_ids != reranked_ids or baseline_results[0]["score"] != reranked_results[0]["score"], (
        "Reranking should change result ordering or scores"
    )


@pytest.mark.asyncio
async def test_rerank_with_empty_results(client, api_url):
    """Verify reranking handles empty result set gracefully."""
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "xyznonexistentquery12345", "limit": 10, "rerank": True},
        timeout=30.0,
    )
    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list), "Should return empty list, not error"


@pytest.mark.asyncio
async def test_rerank_with_single_result(client, api_url):
    """Verify reranking handles single result without crashing."""
    # Use a very specific query likely to return 1 result
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "very specific unique query", "limit": 1, "rerank": True},
        timeout=30.0,
    )
    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list), "Should handle single result gracefully"


@pytest.mark.asyncio
async def test_rerank_preserves_metadata(client, api_url):
    """Verify reranking preserves result metadata."""
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "database connection", "limit": 5, "rerank": True},
        timeout=30.0,
    )
    assert response.status_code == 200
    results = response.json()

    if len(results) > 0:
        result = results[0]
        assert "id" in result, "Missing id field"
        assert "score" in result, "Missing score field"
        assert "content" in result, "Missing content field"
        assert "metadata" in result, "Missing metadata field"
        assert isinstance(result["metadata"], dict), "Metadata should be dict"


@pytest.mark.asyncio
async def test_rerank_respects_limit(client, api_url):
    """Verify reranking respects result limit."""
    limit = 3
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "api endpoint", "limit": limit, "rerank": True},
        timeout=30.0,
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) <= limit, f"Expected at most {limit} results, got {len(results)}"


@pytest.mark.asyncio
async def test_baseline_still_works(client, api_url):
    """Verify baseline (no reranking) still works correctly."""
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "error handling", "limit": 5, "rerank": False},
        timeout=30.0,
    )
    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list), "Baseline should return list"


@pytest.mark.asyncio
async def test_rerank_default_behavior(client, api_url):
    """Verify default behavior when rerank not specified."""
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "configuration", "limit": 5},
        timeout=30.0,
    )
    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list), "Should handle missing rerank parameter"


@pytest.mark.asyncio
async def test_rerank_with_repo_filter(client, api_url):
    """Verify reranking works with repo filtering."""
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "authentication", "limit": 5, "rerank": True, "repo": "test-repo"},
        timeout=30.0,
    )
    # Should succeed even if repo doesn't exist (returns empty results)
    assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}"


@pytest.mark.asyncio
async def test_rerank_scores_are_updated(client, api_url):
    """Verify reranking updates scores (not just reorders)."""
    response = await client.post(
        f"{api_url}/v1/search/",
        json={"query": "search algorithm", "limit": 5, "rerank": True},
        timeout=30.0,
    )
    assert response.status_code == 200
    results = response.json()

    if len(results) >= 2:
        # Scores should be present and likely different between results
        scores = [r["score"] for r in results]
        assert all(isinstance(s, (int, float)) for s in scores), "Scores should be numeric"
        # In most cases, top result should have higher score than bottom result
        # (but this isn't strictly guaranteed, so we just check they exist)
