"""
Integration tests for the core Clew pipeline: Search → Traverse → Verify.

These tests exercise the *combined* workflow that agents actually perform,
rather than testing endpoints in isolation. All external services are mocked
via FastAPI dependency overrides (same as unit tests), but the tests chain
API calls together to validate the complete data flow.

Alpha Blocker: Pre-Release Hardening Item #1
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

# ---------------------------------------------------------------------------
# Richer fixtures that model a realistic codebase graph
# ---------------------------------------------------------------------------

REALISTIC_SEARCH_RESULTS = [
    SearchResult(
        id="file:src/auth/session.py",
        score=0.95,
        content="class SessionManager:\n    def validate(self, token): ...",
        metadata={"path": "src/auth/session.py", "type": "code_chunk", "repo": "acme/backend"},
    ),
    SearchResult(
        id="file:src/auth/middleware.py",
        score=0.88,
        content="class AuthMiddleware:\n    async def __call__(self, request): ...",
        metadata={"path": "src/auth/middleware.py", "type": "code_chunk", "repo": "acme/backend"},
    ),
    SearchResult(
        id="file:src/routes/login.py",
        score=0.72,
        content="@router.post('/login')\nasync def login(credentials): ...",
        metadata={"path": "src/routes/login.py", "type": "code_chunk", "repo": "acme/backend"},
    ),
]

REALISTIC_GRAPH = GraphResult(
    nodes=[
        GraphNode(id="file:src/auth/session.py", label="session.py", properties={"type": "file"}),
        GraphNode(
            id="func:SessionManager.validate",
            label="validate",
            properties={"type": "function"},
        ),
        GraphNode(
            id="file:src/auth/middleware.py",
            label="middleware.py",
            properties={"type": "file"},
        ),
        GraphNode(
            id="file:src/routes/login.py",
            label="login.py",
            properties={"type": "file"},
        ),
    ],
    edges=[
        GraphEdge(
            id="e1",
            source="file:src/auth/session.py",
            target="func:SessionManager.validate",
            type="DEFINES",
            properties={},
        ),
        GraphEdge(
            id="e2",
            source="file:src/auth/middleware.py",
            target="file:src/auth/session.py",
            type="IMPORTS",
            properties={},
        ),
        GraphEdge(
            id="e3",
            source="file:src/routes/login.py",
            target="func:SessionManager.validate",
            type="CALLS",
            properties={},
        ),
    ],
)


@pytest.fixture
def pipeline_vector_store():
    """Vector store with realistic multi-result search data."""
    store = AsyncMock(spec=VectorStore)
    store.search.return_value = REALISTIC_SEARCH_RESULTS
    return store


@pytest.fixture
def pipeline_graph_store():
    """Graph store with realistic multi-hop traversal data."""
    store = AsyncMock(spec=GraphStore)
    store.traverse.return_value = REALISTIC_GRAPH
    return store


@pytest.fixture
def pipeline_embeddings():
    """Embedding provider for the pipeline."""
    provider = AsyncMock(spec=EmbeddingProvider)
    provider.embed.return_value = [0.1] * 1536
    type(provider).dimension = PropertyMock(return_value=1536)
    return provider


@pytest.fixture
def pipeline_app(pipeline_vector_store, pipeline_graph_store, pipeline_embeddings):
    """FastAPI app wired with the pipeline fixtures."""
    app.dependency_overrides[get_vector_store] = lambda: pipeline_vector_store
    app.dependency_overrides[get_graph_store] = lambda: pipeline_graph_store
    app.dependency_overrides[get_embeddings] = lambda: pipeline_embeddings
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def api(pipeline_app):
    """Async HTTP client bound to the pipeline app."""
    transport = ASGITransport(app=pipeline_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ==========================================================================
# Integration: Search → Traverse (the core agent workflow)
# ==========================================================================


class TestSearchThenTraverse:
    """
    Simulate what an AI agent does: search for code, then traverse
    the graph starting from the top search result.
    """

    @pytest.mark.asyncio
    async def test_search_result_ids_are_valid_traverse_inputs(self, api):
        """Search result IDs can be directly used as graph traverse start nodes."""
        # Step 1: Search
        search_resp = await api.post("/v1/search/", json={"query": "session management"})
        assert search_resp.status_code == 200
        results = search_resp.json()
        assert len(results) >= 1

        # Step 2: Traverse from the top result
        top_id = results[0]["metadata"]["path"]
        traverse_resp = await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": top_id},
        )
        assert traverse_resp.status_code == 200
        graph = traverse_resp.json()

        # The graph should contain the start node
        node_ids = [n["id"] for n in graph["nodes"]]
        # Note: Graph nodes have 'file:' prefix, but we traverse by path
        assert f"file:{top_id}" in node_ids

    @pytest.mark.asyncio
    async def test_traverse_reveals_callers_and_dependencies(self, api):
        """Graph traversal from a search result reveals both callers and dependencies."""
        # Search
        search_resp = await api.post("/v1/search/", json={"query": "session"})
        assert search_resp.status_code == 200
        results = search_resp.json()
        top_id = results[0]["metadata"]["path"]

        # Traverse
        traverse_resp = await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": top_id, "depth": 2},
        )
        assert traverse_resp.status_code == 200
        graph = traverse_resp.json()

        # Should have edges showing relationships
        edge_types = {e["type"] for e in graph["edges"]}
        assert "DEFINES" in edge_types or "IMPORTS" in edge_types or "CALLS" in edge_types

        # Should have more than just the start node
        assert len(graph["nodes"]) > 1

    @pytest.mark.asyncio
    async def test_full_pipeline_search_all_top_results_traverse(self, api):
        """
        Full agent workflow: search → traverse top N results → aggregate context.

        This is exactly what `search_codebase` in the MCP server does.
        """
        # Step 1: Search
        search_resp = await api.post(
            "/v1/search/",
            json={"query": "authentication", "limit": 5},
        )
        assert search_resp.status_code == 200
        results = search_resp.json()

        # Step 2: Traverse top 3 (like MCP server does)
        context = []
        for result in results[:3]:
            traverse_resp = await api.post(
                "/v1/graph/traverse",
                json={
                    "start_node_id": result["metadata"]["path"],
                    "relationship_types": ["CALLS", "IMPORTS", "DEFINES", "CONTAINS"],
                },
            )
            assert traverse_resp.status_code == 200
            context.append(
                {
                    "search_result": result,
                    "graph": traverse_resp.json(),
                }
            )

        # Verify we got context for all 3
        assert len(context) == 3
        for entry in context:
            assert "nodes" in entry["graph"]
            assert "edges" in entry["graph"]


# ==========================================================================
# Integration: Search → Verify (the hallucination backstop)
# ==========================================================================


class TestSearchAsVerification:
    """
    The verify_concept MCP tool uses search to check if something exists.
    Test the workflow end-to-end.
    """

    @pytest.mark.asyncio
    async def test_verify_existing_concept(self, api):
        """Verification of an existing concept returns high-confidence matches."""
        resp = await api.post(
            "/v1/search/",
            json={"query": "SessionManager", "limit": 5},
        )
        assert resp.status_code == 200
        results = resp.json()

        # Verification logic: concept exists if results are returned
        assert len(results) > 0
        # Top result should have meaningful confidence
        assert results[0]["score"] > 0.5

    @pytest.mark.asyncio
    async def test_verify_nonexistent_concept(self, api, pipeline_vector_store):
        """Verification of a non-existent concept returns empty results."""
        pipeline_vector_store.search.return_value = []

        resp = await api.post(
            "/v1/search/",
            json={"query": "NonExistentGraphQLResolver", "limit": 5},
        )
        assert resp.status_code == 200
        results = resp.json()

        # Verification fails: no matches
        assert len(results) == 0


# ==========================================================================
# Integration: Error propagation across the pipeline
# ==========================================================================


class TestPipelineErrorPropagation:
    """
    Verify that errors in one stage propagate correctly rather than
    being silently swallowed.
    """

    @pytest.mark.asyncio
    async def test_vector_store_failure_returns_503(self, api, pipeline_vector_store):
        """Vector store crash returns 503, not a silent empty result."""
        pipeline_vector_store.search.side_effect = ConnectionError("Qdrant unreachable")

        resp = await api.post("/v1/search/", json={"query": "anything"})
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_graph_store_failure_returns_503(self, api, pipeline_graph_store):
        """Graph store crash returns 503, not a silent empty result."""
        pipeline_graph_store.traverse.side_effect = ConnectionError("Neo4j unreachable")

        resp = await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": "file:src/auth.py"},
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_embedding_failure_still_allows_search(self, api, pipeline_embeddings):
        """
        Embedding provider failure triggers hash fallback — search still works.
        This is critical: agents should degrade gracefully, not crash.
        """
        pipeline_embeddings.embed.side_effect = RuntimeError("OpenAI API key expired")

        resp = await api.post("/v1/search/", json={"query": "test"})
        # Should succeed via hash-embedding fallback
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_search_succeeds_but_traverse_fails_is_independent(self, api, pipeline_graph_store):
        """
        Search and traverse are independent — a graph failure shouldn't
        affect a preceding successful search.
        """
        # Search works fine
        search_resp = await api.post("/v1/search/", json={"query": "auth"})
        assert search_resp.status_code == 200
        results = search_resp.json()
        assert len(results) > 0

        # But graph is down
        pipeline_graph_store.traverse.side_effect = ConnectionError("Neo4j down")
        traverse_resp = await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": results[0]["metadata"]["path"]},
        )
        assert traverse_resp.status_code == 503

        # Search still works on retry
        retry_resp = await api.post("/v1/search/", json={"query": "auth"})
        assert retry_resp.status_code == 200


# ==========================================================================
# Integration: Multi-hop graph traversal
# ==========================================================================


class TestMultiHopTraversal:
    """
    Test variable-depth graph traversal — the stated differentiator.
    """

    @pytest.mark.asyncio
    async def test_depth_1_traversal(self, api, pipeline_graph_store):
        """Depth 1 passes through to the graph store."""
        await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": "file:src/auth.py", "depth": 1},
        )
        call_kwargs = pipeline_graph_store.traverse.call_args.kwargs
        assert call_kwargs["depth"] == 1

    @pytest.mark.asyncio
    async def test_depth_3_traversal(self, api, pipeline_graph_store):
        """Depth 3 (max) passes through to the graph store."""
        await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": "file:src/auth.py", "depth": 3},
        )
        call_kwargs = pipeline_graph_store.traverse.call_args.kwargs
        assert call_kwargs["depth"] == 3

    @pytest.mark.asyncio
    async def test_depth_exceeding_max_is_rejected(self, api):
        """Depth > 3 is rejected by validation (Pydantic Field le=3)."""
        resp = await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": "file:src/auth.py", "depth": 5},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_depth_zero_is_rejected(self, api):
        """Depth < 1 is rejected by validation (Pydantic Field ge=1)."""
        resp = await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": "file:src/auth.py", "depth": 0},
        )
        assert resp.status_code == 422


# ==========================================================================
# Integration: Relationship type filtering
# ==========================================================================


class TestRelationshipFiltering:
    """
    Test that relationship type filtering works correctly in the pipeline.
    """

    @pytest.mark.asyncio
    async def test_filter_to_imports_only(self, api, pipeline_graph_store):
        """Filtering to IMPORTS only passes through correctly."""
        await api.post(
            "/v1/graph/traverse",
            json={
                "start_node_id": "file:src/auth.py",
                "relationship_types": ["IMPORTS"],
            },
        )
        call_kwargs = pipeline_graph_store.traverse.call_args.kwargs
        assert call_kwargs["relationship_types"] == ["IMPORTS"]

    @pytest.mark.asyncio
    async def test_invalid_relationship_type_rejected(self, api):
        """Invalid relationship types are rejected with 422."""
        resp = await api.post(
            "/v1/graph/traverse",
            json={
                "start_node_id": "file:src/auth.py",
                "relationship_types": ["INHERITS"],
            },
        )
        assert resp.status_code == 422
        assert "INHERITS" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_mixed_valid_invalid_relationship_types_rejected(self, api):
        """Even one invalid type in the list causes rejection."""
        resp = await api.post(
            "/v1/graph/traverse",
            json={
                "start_node_id": "file:src/auth.py",
                "relationship_types": ["IMPORTS", "EXTENDS"],
            },
        )
        assert resp.status_code == 422


# ==========================================================================
# Integration: Search input validation across the pipeline
# ==========================================================================


class TestPipelineInputValidation:
    """
    Verify that validation constraints protect the full pipeline.
    """

    @pytest.mark.asyncio
    async def test_search_query_max_length(self, api):
        """Queries exceeding 1000 chars are rejected."""
        resp = await api.post(
            "/v1/search/",
            json={"query": "x" * 1001},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_limit_max(self, api):
        """Limit exceeding 100 is rejected."""
        resp = await api.post(
            "/v1/search/",
            json={"query": "auth", "limit": 101},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_empty_query_rejected(self, api):
        """Empty query string is rejected."""
        resp = await api.post(
            "/v1/search/",
            json={"query": ""},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_traverse_node_id_max_length(self, api):
        """Node ID exceeding 512 chars is rejected."""
        resp = await api.post(
            "/v1/graph/traverse",
            json={"start_node_id": "x" * 513},
        )
        assert resp.status_code == 422
