"""
Statistics endpoint for Clew Engine.
Returns graph metrics for telemetry.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from clew.server.adapters import GraphStore
from clew.server.dependencies import get_graph_store

router = APIRouter()
logger = logging.getLogger("clew.routes.stats")


class StatsResponse(BaseModel):
    node_count: int
    edge_count: int
    density: float


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    repo_id: str | None = Query(None, description="Optional repository filter"),
    graph_store: GraphStore = Depends(get_graph_store),
):
    """
    Get current graph statistics.
    Used by the Worker for heartbeat telemetry.
    """
    try:
        stats = await graph_store.get_stats(repo_id=repo_id)
        return StatsResponse(
            node_count=stats.get("node_count", 0),
            edge_count=stats.get("edge_count", 0),
            density=stats.get("density", 0.0),
        )
    except Exception as e:
        logger.error(f"Failed to fetch stats: {e}")
        raise HTTPException(status_code=503, detail="Stats unavailable") from e
