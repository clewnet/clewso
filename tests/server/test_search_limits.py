import pytest
from pydantic import ValidationError

from clew.server.routes.search import SearchRequest


def test_search_request_valid_limit():
    """Limit within bounds should be valid."""
    req = SearchRequest(query="test", limit=50)
    assert req.limit == 50


def test_search_request_limit_too_high():
    """Limit > 100 should raise ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SearchRequest(query="test", limit=101)

    assert "less than or equal to 100" in str(exc.value)


def test_search_request_limit_too_low():
    """Limit <= 0 should raise ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SearchRequest(query="test", limit=0)

    assert "greater than 0" in str(exc.value)


def test_search_request_query_too_long():
    """Query > 1000 chars should raise ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SearchRequest(query="a" * 1001)

    assert "at most 1000 characters" in str(exc.value)


def test_search_request_query_too_short():
    """Query < 1 char (empty) should raise ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SearchRequest(query="")

    assert "at least 1 character" in str(exc.value)


def test_search_request_repo_too_long():
    """Repo > 512 chars should raise ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SearchRequest(query="valid", repo="a" * 513)

    assert "at most 512 characters" in str(exc.value)


@pytest.mark.asyncio
async def test_search_endpoint_limit_validation(client):
    """API endpoint should return 422 for invalid limit."""
    resp = await client.post("/v1/search/", json={"query": "test", "limit": 1000})
    assert resp.status_code == 422

    data = resp.json()
    assert data["detail"][0]["msg"] == "Input should be less than or equal to 100"
