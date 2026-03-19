"""
Shared test fixtures for Clew Engine API tests.

All adapters (VectorStore, GraphStore, EmbeddingProvider) are mocked via
FastAPI dependency overrides — no external services needed.
"""

from unittest.mock import AsyncMock, PropertyMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from clew.server.adapters.base import (
    EmbeddingProvider,
    GraphEdge,
    GraphNode,
    GraphResult,
    GraphStore,
    SearchResult,
    VectorStore,
)
from clew.server.dependencies import get_embeddings, get_graph_store, get_vector_store
from clew.server.main import app


@pytest.fixture
def mock_vector_store():
    """Mock VectorStore that returns canned search results."""
    store = AsyncMock(spec=VectorStore)
    store.search.return_value = [
        SearchResult(
            id="file:src/auth.py",
            score=0.92,
            content="def validate_session(token): ...",
            metadata={"path": "src/auth.py", "type": "code_chunk", "repo": "owner/repo"},
        ),
        SearchResult(
            id="file:src/middleware.py",
            score=0.85,
            content="class AuthMiddleware: ...",
            metadata={"path": "src/middleware.py", "type": "code_chunk", "repo": "owner/repo"},
        ),
    ]
    return store


@pytest.fixture
def mock_graph_store():
    """Mock GraphStore that returns canned traversal results."""
    store = AsyncMock(spec=GraphStore)
    store.traverse.return_value = GraphResult(
        nodes=[
            GraphNode(id="file:src/auth.py", label="auth.py", properties={"type": "file"}),
            GraphNode(
                id="func:validate_session",
                label="validate_session",
                properties={"type": "function"},
            ),
        ],
        edges=[
            GraphEdge(
                id="e1",
                source="file:src/auth.py",
                target="func:validate_session",
                type="DEFINES",
                properties={},
            ),
        ],
    )
    return store


@pytest.fixture
def mock_embeddings():
    """Mock EmbeddingProvider that returns a fixed-dimension vector."""
    provider = AsyncMock(spec=EmbeddingProvider)
    provider.embed.return_value = [0.1] * 1536
    type(provider).dimension = PropertyMock(return_value=1536)
    return provider


@pytest.fixture
def test_app(mock_vector_store, mock_graph_store, mock_embeddings):
    """FastAPI app with all adapters overridden by mocks."""
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    app.dependency_overrides[get_graph_store] = lambda: mock_graph_store
    app.dependency_overrides[get_embeddings] = lambda: mock_embeddings
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app):
    """Async HTTP client bound to the test app."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
