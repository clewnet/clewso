from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client.http import models

from clew.server.adapters.qdrant import QdrantStore, _check_protocol


@pytest.fixture
def mock_qdrant_client():
    with patch("clew.server.adapters.qdrant.AsyncQdrantClient") as mock_client_cls:
        client_instance = AsyncMock()
        mock_client_cls.return_value = client_instance
        yield client_instance


@pytest.fixture
def store(mock_qdrant_client):
    return QdrantStore(host="localhost", port=6333, collection_name="test_collection")


@pytest.mark.asyncio
async def test_lazy_initialization(store, mock_qdrant_client):
    assert store._client is None
    client = store.client
    assert client is mock_qdrant_client
    assert store._client is not None


@pytest.mark.asyncio
async def test_search_basic(store, mock_qdrant_client):
    # Setup mock response
    point = MagicMock()
    point.id = "point_id"
    point.score = 0.95
    point.payload = {"text": "some content", "other": "meta"}

    result_obj = MagicMock()
    result_obj.points = [point]

    mock_qdrant_client.query_points.return_value = result_obj

    query_vector = [0.1, 0.2, 0.3]
    results = await store.search(query_vector, limit=5)

    assert len(results) == 1
    assert results[0].id == "point_id"
    assert results[0].score == 0.95
    assert results[0].content == "some content"
    assert results[0].metadata == {"text": "some content", "other": "meta"}

    mock_qdrant_client.query_points.assert_called_once()
    call_kwargs = mock_qdrant_client.query_points.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_collection"
    assert call_kwargs["query"] == query_vector
    assert call_kwargs["limit"] == 5
    assert call_kwargs["query_filter"] is None


@pytest.mark.asyncio
async def test_search_with_filters(store, mock_qdrant_client):
    # Setup mock response
    result_obj = MagicMock()
    result_obj.points = []
    mock_qdrant_client.query_points.return_value = result_obj

    query_vector = [0.1]
    filters = {"path": "some/path.py", "path_contains": "path", "type": "function"}

    await store.search(query_vector, repo="my/repo", filters=filters)

    call_kwargs = mock_qdrant_client.query_points.call_args.kwargs
    query_filter = call_kwargs["query_filter"]

    assert isinstance(query_filter, models.Filter)
    must = query_filter.must
    assert len(must) == 4  # repo + 3 filters

    # Check repo filter (payload field is repo_id)
    repo_cond = next(c for c in must if c.key == "repo_id")
    assert repo_cond.match.value == "my/repo"

    # Check path filter
    path_cond = next(c for c in must if c.key == "path" and isinstance(c.match, models.MatchValue))
    assert path_cond.match.value == "some/path.py"

    # Check path_contains filter
    contains_cond = next(c for c in must if c.key == "path" and isinstance(c.match, models.MatchText))
    assert contains_cond.match.text == "path"

    # Check type filter
    type_cond = next(c for c in must if c.key == "type")
    assert type_cond.match.value == "function"


def test_check_protocol():
    # Just ensure it doesn't raise error
    with patch("clew.server.adapters.qdrant.AsyncQdrantClient"):
        _check_protocol()
