"""
Graph traversal endpoint - refactored to use adapters.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from clew.server.adapters import GraphStore
from clew.server.dependencies import get_graph_store

router = APIRouter()
logger = logging.getLogger("clew.routes.graph")

ALLOWED_RELATIONSHIPS = {"IMPORTS", "CALLS", "CONTAINS", "DEFINES"}


class GraphQueryRequest(BaseModel):
    start_node_id: str = Field(..., max_length=512)
    depth: int = Field(2, ge=1, le=3)
    relationship_types: list[str] = Field(default=["IMPORTS", "CALLS", "CONTAINS", "DEFINES"])
    repo_id: str | None = Field(default=None, description="Optional repository ID to scope traversal")


class GraphNodeResponse(BaseModel):
    id: str
    label: str
    properties: dict


class GraphEdgeResponse(BaseModel):
    id: str
    source: str
    target: str
    type: str
    properties: dict


class GraphResponse(BaseModel):
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


@router.post("/traverse", response_model=GraphResponse)
async def traverse_graph(request: GraphQueryRequest, graph_store: GraphStore = Depends(get_graph_store)):
    """
    Traverse the code graph from a starting node.

    Uses injected GraphStore adapter, making the endpoint
    pluggable for different graph backends.
    """
    # Validate relationship types against allowlist
    invalid_types = [t for t in request.relationship_types if t not in ALLOWED_RELATIONSHIPS]
    if invalid_types:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid relationship types: {', '.join(invalid_types)}. Allowed: {', '.join(ALLOWED_RELATIONSHIPS)}"
            ),
        )

    try:
        result = await graph_store.traverse(
            start_id=request.start_node_id,
            depth=request.depth,
            relationship_types=request.relationship_types,
            repo_id=request.repo_id,
        )
    except Exception as e:
        logger.error(f"Graph traversal failed: {e}")
        raise HTTPException(status_code=503, detail="Graph service unavailable") from e

    return GraphResponse(
        nodes=[GraphNodeResponse(id=n.id, label=n.label, properties=n.properties) for n in result.nodes],
        edges=[
            GraphEdgeResponse(id=e.id, source=e.source, target=e.target, type=e.type, properties=e.properties)
            for e in result.edges
        ],
    )


@router.get("/file/{file_path:path}/pull_requests", response_model=list[GraphNodeResponse])
async def get_file_pull_requests(
    file_path: str,
    repo_id: str | None = None,
    graph_store: GraphStore = Depends(get_graph_store),
):
    """
    Get all PRs that modified a specific file.

    Args:
        file_path: Path of the file (can include slashes)
        repo_id: Optional repository ID filter
        graph_store: Injected graph store
    """
    try:
        nodes = await graph_store.get_file_pull_requests(file_path, repo_id=repo_id)
        return [GraphNodeResponse(id=n.id, label=n.label, properties=n.properties) for n in nodes]
    except Exception as e:
        logger.error(f"Failed to get PRs for file {file_path}: {e}")
        raise HTTPException(status_code=503, detail="Graph service unavailable") from e


@router.get("/pull_request/{pr_number}/impact", response_model=GraphResponse)
async def get_pr_impact(
    pr_number: int,
    repo_id: str,
    graph_store: GraphStore = Depends(get_graph_store),
):
    """
    Get the impact of a PR (files and functions modified).

    Args:
        pr_number: PR number
        repo_id: Repository ID
        graph_store: Injected graph store
    """
    try:
        result = await graph_store.get_pr_impact(pr_number, repo_id)
        return GraphResponse(
            nodes=[GraphNodeResponse(id=n.id, label=n.label, properties=n.properties) for n in result.nodes],
            edges=[
                GraphEdgeResponse(id=e.id, source=e.source, target=e.target, type=e.type, properties=e.properties)
                for e in result.edges
            ],
        )
    except Exception as e:
        logger.error(f"Failed to get impact for PR #{pr_number}: {e}")
        raise HTTPException(status_code=503, detail="Graph service unavailable") from e
