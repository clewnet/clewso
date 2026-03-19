"""
Tests for the /v1/graph/traverse endpoint.
"""

import pytest

from clew.server.adapters.base import GraphResult


@pytest.mark.asyncio
async def test_traverse_returns_nodes_and_edges(client, mock_graph_store):
    """Traverse endpoint returns graph structure from graph store."""
    resp = await client.post(
        "/v1/graph/traverse",
        json={"start_node_id": "file:src/auth.py"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["nodes"][0]["id"] == "file:src/auth.py"
    assert data["edges"][0]["type"] == "DEFINES"
    assert data["edges"][0]["source"] == "file:src/auth.py"
    assert data["edges"][0]["target"] == "func:validate_session"


@pytest.mark.asyncio
async def test_traverse_passes_depth(client, mock_graph_store):
    """Depth parameter is forwarded to graph store."""
    await client.post(
        "/v1/graph/traverse",
        json={"start_node_id": "file:src/auth.py", "depth": 3},
    )

    call_kwargs = mock_graph_store.traverse.call_args.kwargs
    assert call_kwargs["depth"] == 3


@pytest.mark.asyncio
async def test_traverse_passes_relationship_types(client, mock_graph_store):
    """Custom relationship_types are forwarded to graph store."""
    await client.post(
        "/v1/graph/traverse",
        json={
            "start_node_id": "file:src/auth.py",
            "relationship_types": ["CALLS", "IMPORTS"],
        },
    )

    call_kwargs = mock_graph_store.traverse.call_args.kwargs
    assert call_kwargs["relationship_types"] == ["CALLS", "IMPORTS"]


@pytest.mark.asyncio
async def test_traverse_uses_default_relationship_types(client, mock_graph_store):
    """Default relationship types include IMPORTS, CALLS, CONTAINS, DEFINES."""
    await client.post(
        "/v1/graph/traverse",
        json={"start_node_id": "file:src/auth.py"},
    )

    call_kwargs = mock_graph_store.traverse.call_args.kwargs
    assert set(call_kwargs["relationship_types"]) == {"IMPORTS", "CALLS", "CONTAINS", "DEFINES"}


@pytest.mark.asyncio
async def test_traverse_empty_graph(client, mock_graph_store):
    """Empty graph result returns empty nodes and edges lists."""
    mock_graph_store.traverse.return_value = GraphResult(nodes=[], edges=[])

    resp = await client.post(
        "/v1/graph/traverse",
        json={"start_node_id": "file:nonexistent.py"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []


@pytest.mark.asyncio
async def test_traverse_forwards_repo_id(client, mock_graph_store):
    """repo_id is forwarded from request to graph store."""
    await client.post(
        "/v1/graph/traverse",
        json={"start_node_id": "file:src/auth.py", "repo_id": "my-repo"},
    )

    call_kwargs = mock_graph_store.traverse.call_args.kwargs
    assert call_kwargs["repo_id"] == "my-repo"


@pytest.mark.asyncio
async def test_traverse_repo_id_defaults_to_none(client, mock_graph_store):
    """repo_id defaults to None when not provided in request."""
    await client.post(
        "/v1/graph/traverse",
        json={"start_node_id": "file:src/auth.py"},
    )

    call_kwargs = mock_graph_store.traverse.call_args.kwargs
    assert call_kwargs["repo_id"] is None


@pytest.mark.asyncio
async def test_traverse_validation_rejects_missing_start_node(client):
    """Request without start_node_id returns 422."""
    resp = await client.post(
        "/v1/graph/traverse",
        json={"depth": 2},
    )

    assert resp.status_code == 422
