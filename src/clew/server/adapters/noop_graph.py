"""
NoOp Graph Store Adapter

A stub implementation of GraphStore for deployments that don't need graph traversal.
This enables Clew to work with just a vector database (e.g., pgvector-only).

Use cases:
- Customers who only want semantic search
- Simplified deployments without Neo4j
- Testing and development
"""

import logging
import uuid
from typing import TYPE_CHECKING, Any

from .base import GraphNode, GraphResult, GraphStats, GraphStore, PRData

logger = logging.getLogger("clew.adapters.noop")


class NoOpGraphStore(GraphStore):
    """
    No-operation implementation of GraphStore protocol.

    Returns empty results for all operations. Use this when you want
    Clew to function without a graph database.

    Environment:
        CLEW_GRAPH_ADAPTER=noop
    """

    def __init__(self):
        logger.info("NoOpGraphStore initialized - graph traversal disabled")

    async def traverse(
        self, start_id: str, depth: int = 2, relationship_types: list[str] | None = None, repo_id: str | None = None
    ) -> GraphResult:
        """
        Return an empty graph result with a note that graph is disabled.

        This allows the API to function without graph capabilities,
        while making it clear to consumers that they're in vector-only mode.
        """
        logger.debug(f"NoOp traverse called for {start_id} (graph disabled)")

        # Return a stub result that includes the start node info
        return GraphResult(
            nodes=[
                GraphNode(
                    id=start_id,
                    label="File",
                    properties={
                        "path": start_id,
                        "note": "Graph traversal disabled - vector-only mode",
                    },
                )
            ],
            edges=[],
        )

    async def create_node(self, node_type: str, properties: dict[str, Any]) -> str:
        """
        No-op node creation. Returns the ID from properties if present.
        """
        node_id = properties.get("id") or properties.get("path") or str(uuid.uuid4())
        logger.debug(f"NoOp create_node: {node_type} -> {node_id}")
        return node_id

    async def create_relationship(
        self, source_id: str, target_id: str, rel_type: str, properties: dict[str, Any] | None = None
    ) -> None:
        """
        No-op relationship creation. Does nothing.
        """
        logger.debug(f"NoOp create_relationship: {source_id} -[{rel_type}]-> {target_id}")
        pass

    async def create_pr_node(self, pr_data: PRData) -> str:
        """No-op PR creation."""
        logger.debug(f"NoOp create_pr_node: {pr_data.get('number')}")
        return str(uuid.uuid4())

    async def link_pr_to_files(self, pr_number: int, repo_id: str, file_paths: list[str]) -> None:
        """No-op linking."""
        logger.debug(f"NoOp link_pr_to_files: {pr_number} in {repo_id} -> {len(file_paths)} files")
        pass

    async def get_file_pull_requests(self, file_path: str, repo_id: str | None = None) -> list[GraphNode]:
        """No-op PR retrieval."""
        logger.debug(f"NoOp get_file_pull_requests: {file_path} in {repo_id}")
        return []

    async def get_pr_impact(self, pr_number: int, repo_id: str) -> GraphResult:
        """No-op impact analysis."""
        logger.debug(f"NoOp get_pr_impact: {pr_number} in {repo_id}")
        return GraphResult(nodes=[], edges=[])

    async def get_neighbors_batch(self, paths: list[str], repo_id: str | None = None) -> dict[str, list[str]]:
        """No-op neighbor lookup."""
        logger.debug(f"NoOp get_neighbors_batch: {len(paths)} paths")
        return {p: [] for p in paths}

    async def get_stats(self, repo_id: str | None = None) -> GraphStats:
        """No-op stats retrieval."""
        logger.debug("NoOp get_stats called")
        return {"node_count": 0, "edge_count": 0, "density": 0.0}

    async def create_policy(self, policy: dict[str, Any]) -> str:
        """No-op policy creation."""
        logger.debug(f"NoOp create_policy: {policy.get('id')}")
        return policy.get("id", "noop")

    async def get_policies(self) -> list[dict[str, Any]]:
        """No-op policy retrieval."""
        logger.debug("NoOp get_policies called")
        return []

    async def delete_policy(self, policy_id: str) -> bool:
        """No-op policy deletion."""
        logger.debug(f"NoOp delete_policy: {policy_id}")
        return False

    async def close(self) -> None:
        """No resources to close."""
        pass


if TYPE_CHECKING:
    # Type check: ensure NoOpGraphStore implements GraphStore
    def _check_protocol() -> GraphStore:
        return NoOpGraphStore()  # type: ignore


# =============================================================================
# Auto-registration
# =============================================================================


def _register_noop():
    """Register NoOp graph adapter with the registry."""
    from . import registry

    def factory() -> NoOpGraphStore:
        return NoOpGraphStore()

    registry.graph_store_registry.register("noop", factory)


# Auto-register on module import
try:
    _register_noop()
    logger.debug("Registered NoOp graph adapter")
except Exception as e:
    logger.debug(f"Skipping NoOp auto-registration: {e}")
