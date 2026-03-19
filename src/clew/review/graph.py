import logging
from dataclasses import dataclass
from datetime import datetime

from ..client import ClewAPIClient

logger = logging.getLogger("clew.review.graph")


@dataclass
class ImpactedFile:
    path: str
    node_id: str
    incoming_edges: int
    relationship: str
    score: float = 0.0


async def get_impact_radius(client: ClewAPIClient, file_path: str, limit: int = 10) -> list[ImpactedFile]:
    """
    Finds files that depend on the given file path (Reverse Dependency Search).

    Args:
        client: Authenticated ClewAPIClient
        file_path: Relative path of the changed file
        limit: Max number of files to return (top N by criticality)

    Returns:
        List of ImpactedFile objects sorted by criticality score.
    """
    start_time = datetime.now()

    # 1. Find the Node ID for the file
    node_id = await _find_node_id(client, file_path)
    if not node_id:
        return []

    # 2. Traverse Incoming Edges
    graph = await client.traverse(str(node_id), relationship_types=["IMPORTS", "CALLS"], depth=1)

    # 3. Analyze Edges
    impacted = _analyze_impact_edges(graph, str(node_id))

    # 4. Global Criticality Ranking
    critical_patterns = ["auth", "payment", "billing", "security", "core", "main"]

    results = list(impacted.values())
    for f in results:
        # Boost for Critical Paths
        if any(p in f.path.lower() for p in critical_patterns):
            f.score += 5.0

    # Sort by score descending
    results.sort(key=lambda x: x.score, reverse=True)

    # Metrics
    duration = (datetime.now() - start_time).total_seconds() * 1000
    logger.info(f"Impact analysis for {file_path}: Found {len(results)} consumers in {duration:.2f}ms")

    if len(results) > limit:
        logger.info(f"Truncating results from {len(results)} to {limit}")
        return results[:limit]

    return results


async def _find_node_id(client: ClewAPIClient, file_path: str) -> str | None:
    """Find the best matching node ID for a file path."""
    logger.debug(f"Searching for node: {file_path}")
    search_results = await client.search(file_path, limit=5, filters={"path": file_path})

    # Try to find exact match in results
    for res in search_results:
        res_path = res.get("metadata", {}).get("path")
        if res_path == file_path or res_path.endswith(f"/{file_path}"):
            return res.get("id")

    # Fallback: Just take the first result if highly similar?
    if search_results:
        # Loose match heuristic
        target_node = search_results[0]
        logger.warning(f"No exact match for {file_path}, using closest: {target_node.get('metadata', {}).get('path')}")
        return target_node.get("id")

    logger.info(f"File {file_path} not found in graph. Assuming new file or ignored.")
    return None


def _analyze_impact_edges(graph: dict, node_id: str) -> dict[str, ImpactedFile]:
    """Analyze incoming edges to find impacted files."""
    nodes_map = {n["id"]: n for n in graph.get("nodes", [])}
    impacted: dict[str, ImpactedFile] = {}

    for edge in graph.get("edges", []):
        if edge["target"] != node_id:
            continue

        source_id = edge["source"]
        source_node = nodes_map.get(source_id)

        if not source_node:
            continue

        source_path = source_node.get("metadata", {}).get("path")
        if not source_path:
            continue

        # Skip self-references
        if source_id == node_id:
            continue

        # Update or Create entry
        if source_id not in impacted:
            impacted[source_id] = ImpactedFile(
                path=source_path,
                node_id=source_id,
                incoming_edges=0,
                relationship=edge["type"],
            )

        impacted[source_id].score += 1.0

    return impacted
