"""
Neo4j Graph Store Adapter

Implements the GraphStore protocol for Neo4j.
"""

import logging
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

from .base import GraphEdge, GraphNode, GraphResult, GraphStats, PRData

logger = logging.getLogger("clew.adapters.neo4j")


class Neo4jStore:
    """Neo4j implementation of GraphStore protocol."""

    def __init__(self, uri: str, user: str, password: str):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None

    @property
    def driver(self):
        """Lazy-initialize the Neo4j driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    def close(self):
        """Close the driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    async def traverse(
        self, start_id: str, depth: int = 2, relationship_types: list[str] | None = None, repo_id: str | None = None
    ) -> GraphResult:
        """
        Traverse the graph from a starting node.

        Args:
            start_id: The path of the starting node
            depth: How many hops to traverse (1-3 supported)
            relationship_types: Edge types to include
            repo_id: Optional repository ID to scope traversal to a single repo

        Returns:
            GraphResult with nodes and edges within the specified depth
        """
        if relationship_types is None:
            relationship_types = ["IMPORTS", "CALLS", "CONTAINS", "DEFINES"]

        # Final safety check against Cypher injection for relationship types
        allowed = {"IMPORTS", "CALLS", "CONTAINS", "DEFINES"}
        filtered_types = [t for t in relationship_types if t in allowed]

        if not filtered_types:
            logger.warning("No valid relationship types provided, defaulting to all allowed types")
            filtered_types = list(allowed)

        # Clamp depth to reasonable range (matching Platform DGT)
        depth = max(1, min(depth, 3))

        # Build source match pattern — include repo_id filter when provided
        if repo_id:
            source_match = "(source {path: $start_node_id, repo_id: $repo_id})"
        else:
            source_match = "(source {path: $start_node_id})"

        # Build variable-length path query
        # Uses [*1..depth] to find all paths within depth hops
        # UNWIND extracts individual relationships to maintain row-per-edge structure
        query = f"""
        MATCH path = {source_match}-[*1..{depth}]-(target)
        WHERE ALL(r IN relationships(path) WHERE type(r) IN $rel_types)
        WITH path
        UNWIND relationships(path) AS rel
        WITH DISTINCT rel
        RETURN
            COALESCE(startNode(rel).path, startNode(rel).name, 'unknown') AS source_path,
            labels(startNode(rel))[0] AS source_label,
            properties(startNode(rel)) AS source_props,
            type(rel) AS rel_type,
            elementId(rel) AS rel_id,
            properties(rel) AS rel_props,
            COALESCE(endNode(rel).path, endNode(rel).name, 'unknown') AS target_path,
            labels(endNode(rel))[0] AS target_label,
            properties(endNode(rel)) AS target_props
        LIMIT 100
        """

        nodes = {}  # Dedupe by ID
        edges = []

        try:
            with self.driver.session() as session:
                result = session.run(query, start_node_id=start_id, rel_types=filtered_types, repo_id=repo_id)  # type: ignore[arg-type]
                for record in result:
                    source_path = record["source_path"] or "unknown"
                    target_path = record["target_path"] or "unknown"

                    # Add source node
                    if source_path not in nodes:
                        nodes[source_path] = self._parse_node(record, "source")

                    # Add target node
                    if target_path not in nodes:
                        nodes[target_path] = self._parse_node(record, "target")

                    # Add edge
                    edges.append(self._parse_edge(record, source_path, target_path))

        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j traversal failed: {e}", exc_info=True)
            raise

        # Deduplicate edges
        unique_edges = {e.id: e for e in edges}.values()

        return GraphResult(nodes=list(nodes.values()), edges=list(unique_edges))

    def _parse_node(self, record, prefix: str) -> GraphNode:
        """Helper to parse a node from a Neo4j record."""
        path_key = f"{prefix}_path"
        label_key = f"{prefix}_label"
        props_key = f"{prefix}_props"

        return GraphNode(
            id=record[path_key] or "unknown",
            label=record[label_key] or "Unknown",
            properties=dict(record[props_key]) if record[props_key] else {},
        )

    def _parse_edge(self, record, source_id: str, target_id: str) -> GraphEdge:
        """Helper to parse an edge from a Neo4j record."""
        return GraphEdge(
            id=record["rel_id"],
            source=source_id,
            target=target_id,
            type=record["rel_type"],
            properties=dict(record["rel_props"]) if record["rel_props"] else {},
        )

    def _get_element_id(self, entity):
        """Helper to get element_id from node or relationship, falling back to id."""
        val = getattr(entity, "element_id", None)
        if val is not None:
            return val
        return str(entity.id)

    async def create_pr_node(self, pr_data: PRData) -> str:
        """Create a PullRequest node."""
        query = """
        MERGE (pr:PullRequest {number: $number, repo_id: $repo_id})
        SET pr.title = $title,
            pr.url = $url,
            pr.state = $state,
            pr.author = $author,
            pr.created_at = $created_at,
            pr.base_branch = $base_branch,
            pr.head_branch = $head_branch
        WITH pr
        MATCH (r:Repository {id: $repo_id})
        MERGE (pr)-[:BELONGS_TO]->(r)
        RETURN elementId(pr) as id
        """

        try:
            with self.driver.session() as session:
                result = session.run(
                    query,
                    number=pr_data.get("number"),
                    repo_id=pr_data.get("repo_id"),
                    title=pr_data.get("title", ""),
                    url=pr_data.get("url", ""),
                    state=pr_data.get("state", ""),
                    author=pr_data.get("author", ""),
                    created_at=pr_data.get("created_at", ""),
                    base_branch=pr_data.get("base_branch", ""),
                    head_branch=pr_data.get("head_branch", ""),
                )
                record = result.single()
                return record["id"] if record else ""
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j create_pr_node failed: {e}", exc_info=True)
            raise

    async def link_pr_to_files(self, pr_number: int, repo_id: str, file_paths: list[str]) -> None:
        """Link PR to files."""
        query = """
        MATCH (pr:PullRequest {number: $number, repo_id: $repo_id})
        UNWIND $file_paths AS file_path
        MATCH (f:File {path: file_path, repo_id: $repo_id})
        MERGE (pr)-[:MODIFIES]->(f)
        """

        try:
            with self.driver.session() as session:
                session.run(query, number=pr_number, repo_id=repo_id, file_paths=file_paths)
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j link_pr_to_files failed: {e}", exc_info=True)
            raise

    async def get_file_pull_requests(self, file_path: str, repo_id: str | None = None) -> list[GraphNode]:
        """Get PRs for a file."""
        if repo_id:
            query = """
            MATCH (pr:PullRequest)-[:MODIFIES]->(f:File {path: $file_path, repo_id: $repo_id})
            RETURN pr
            LIMIT 50
            """
        else:
            query = """
            MATCH (pr:PullRequest)-[:MODIFIES]->(f:File {path: $file_path})
            RETURN pr
            LIMIT 50
            """

        try:
            with self.driver.session() as session:
                result = session.run(query, file_path=file_path, repo_id=repo_id)
                nodes = []
                for record in result:
                    node = record["pr"]
                    node_id = self._get_element_id(node)
                    nodes.append(
                        GraphNode(
                            id=node_id,
                            label="PullRequest",
                            properties=dict(node),
                        )
                    )
                return nodes
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j get_file_pull_requests failed: {e}", exc_info=True)
            raise

    def _parse_pr_impact_record(self, record, nodes, edges):
        """Helper to parse nodes and edges from PR impact record."""
        f_node = record["f"]
        pr_node = record["pr"]
        c_node = record["c"]
        r1 = record["r1"]
        r2 = record["r2"]

        # Parse PR node
        if pr_node:
            pr_id = self._get_element_id(pr_node)
            if pr_id not in nodes:
                nodes[pr_id] = GraphNode(id=pr_id, label="PullRequest", properties=dict(pr_node))

        # Parse File node
        if f_node:
            f_id = self._get_element_id(f_node)
            if f_id not in nodes:
                nodes[f_id] = GraphNode(id=f_id, label="File", properties=dict(f_node))

            # Edge PR -> File
            if pr_node and r1:
                edge_id = self._get_element_id(r1)
                pr_id = self._get_element_id(pr_node)
                edges.append(
                    GraphEdge(
                        id=edge_id,
                        source=pr_id,
                        target=f_id,
                        type="MODIFIES",
                        properties=dict(r1),
                    )
                )

        # Parse CodeBlock node
        if c_node:
            c_id = self._get_element_id(c_node)
            if c_id not in nodes:
                nodes[c_id] = GraphNode(
                    id=c_id,
                    label=list(c_node.labels)[0] if c_node.labels else "CodeBlock",
                    properties=dict(c_node),
                )

            # Edge File -> CodeBlock
            if f_node and r2:
                edge_id = self._get_element_id(r2)
                f_id = self._get_element_id(f_node)
                edges.append(
                    GraphEdge(
                        id=edge_id,
                        source=f_id,
                        target=c_id,
                        type="DEFINES",
                        properties=dict(r2),
                    )
                )

    async def get_pr_impact(self, pr_number: int, repo_id: str) -> GraphResult:
        """Get impact of a PR."""
        query = """
        MATCH (pr:PullRequest {number: $number, repo_id: $repo_id})
        MATCH (pr)-[r1:MODIFIES]->(f:File)
        OPTIONAL MATCH (f)-[r2:DEFINES]->(c:CodeBlock)
        RETURN f, r1, pr, r2, c
        LIMIT 100
        """

        try:
            with self.driver.session() as session:
                result = session.run(query, number=pr_number, repo_id=repo_id)
                nodes: dict[str, GraphNode] = {}
                edges: list[GraphEdge] = []

                for record in result:
                    self._parse_pr_impact_record(record, nodes, edges)

                unique_edges = {e.id: e for e in edges}.values()
                return GraphResult(nodes=list(nodes.values()), edges=list(unique_edges))

        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j get_pr_impact failed: {e}", exc_info=True)
            raise

    async def get_neighbors_batch(self, paths: list[str], repo_id: str | None = None) -> dict[str, list[str]]:
        """Return {path: [neighbor_paths]} for all given paths in one Cypher query.

        The graph schema is File-[:IMPORTS]->Module and File-[:CALLS]->Function,
        so there are no direct File-to-File edges.  This query performs a 2-hop
        traversal through the intermediate Module/Function node to find other
        Files that share a dependency.
        """
        if not paths:
            return {}

        if repo_id:
            query = """
            UNWIND $paths AS p
            MATCH (f:File {path: p, repo_id: $repo_id})
                  -[:IMPORTS|CALLS]->(mid)
                  <-[:IMPORTS|CALLS|DEFINES]-(neighbor:File)
            WHERE neighbor.path <> p
            RETURN p AS source, collect(DISTINCT neighbor.path) AS neighbors
            """
        else:
            query = """
            UNWIND $paths AS p
            MATCH (f:File {path: p})
                  -[:IMPORTS|CALLS]->(mid)
                  <-[:IMPORTS|CALLS|DEFINES]-(neighbor:File)
            WHERE neighbor.path <> p
            RETURN p AS source, collect(DISTINCT neighbor.path) AS neighbors
            """

        result_map: dict[str, list[str]] = {p: [] for p in paths}

        try:
            with self.driver.session() as session:
                result = session.run(query, paths=paths, repo_id=repo_id)
                for record in result:
                    result_map[record["source"]] = record["neighbors"]
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j get_neighbors_batch failed: {e}", exc_info=True)
            # Return empty neighbors on failure — graph boost degrades gracefully
            return result_map

        return result_map

    async def get_stats(self, repo_id: str | None = None) -> GraphStats:
        """Get graph statistics."""
        if repo_id is not None:
            query_nodes = "MATCH (n {repo_id: $repo_id}) RETURN count(n) as count"
            query_edges = "MATCH (n {repo_id: $repo_id})-[r]->() RETURN count(r) as count"
            params: dict = {"repo_id": repo_id}
        else:
            query_nodes = "MATCH (n) RETURN count(n) as count"
            query_edges = "MATCH ()-[r]->() RETURN count(r) as count"
            params = {}

        try:
            with self.driver.session() as session:
                node_result = session.run(query_nodes, **params)
                edge_result = session.run(query_edges, **params)

                node_row = node_result.single()
                edge_row = edge_result.single()

                node_count = node_row["count"] if node_row else 0
                edge_count = edge_row["count"] if edge_row else 0

                # Calculate density (E / (N * (N-1))) for directed graph
                # Simplified density: E / N (average degree)
                density = 0.0
                if node_count > 1:
                    density = edge_count / (node_count * (node_count - 1))

                return {
                    "node_count": node_count,
                    "edge_count": edge_count,
                    "density": round(density, 6),
                }
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j get_stats failed: {e}", exc_info=True)
            return {"node_count": 0, "edge_count": 0, "density": 0.0}

    async def create_policy(self, policy: dict[str, Any]) -> str:
        """Create or update a PolicyRule node."""
        query = """
        MERGE (p:PolicyRule {id: $id})
        SET p.type = $type,
            p.pattern = $pattern,
            p.severity = $severity,
            p.message = $message,
            p.precept_id = $precept_id
        RETURN p.id AS id
        """
        try:
            with self.driver.session() as session:
                result = session.run(
                    query,
                    id=policy["id"],
                    type=policy["type"],
                    pattern=policy["pattern"],
                    severity=policy["severity"],
                    message=policy["message"],
                    precept_id=policy.get("precept_id"),
                )
                record = result.single()
                return record["id"] if record else policy["id"]
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j create_policy failed: {e}", exc_info=True)
            raise

    async def get_policies(self) -> list[dict[str, Any]]:
        """Return all active PolicyRule nodes."""
        query = """
        MATCH (p:PolicyRule)
        RETURN p.id AS id, p.type AS type, p.pattern AS pattern,
               p.severity AS severity, p.message AS message,
               p.precept_id AS precept_id
        ORDER BY p.id
        """
        try:
            with self.driver.session() as session:
                result = session.run(query)
                return [dict(record) for record in result]
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j get_policies failed: {e}", exc_info=True)
            raise

    async def delete_policy(self, policy_id: str) -> bool:
        """Delete a PolicyRule node by ID."""
        query = """
        MATCH (p:PolicyRule {id: $id})
        DELETE p
        RETURN count(*) AS deleted
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, id=policy_id)
                record = result.single()
                return bool(record and record["deleted"] > 0)
        except (Neo4jError, ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j delete_policy failed: {e}", exc_info=True)
            raise


# =============================================================================
# Auto-registration
# =============================================================================


def _register_neo4j():
    """Register Neo4j adapter with the registry."""
    from ..config import settings
    from . import registry

    def factory() -> Neo4jStore:
        if not settings.NEO4J_USER or not settings.NEO4J_PASSWORD:
            raise ValueError("NEO4J_USER and NEO4J_PASSWORD must be set when using neo4j adapter")
        return Neo4jStore(uri=settings.NEO4J_URI, user=settings.NEO4J_USER, password=settings.NEO4J_PASSWORD)

    registry.graph_store_registry.register("neo4j", factory)


# Auto-register on module import
try:
    _register_neo4j()
    logger.debug("Registered Neo4j adapter")
except Exception as e:
    logger.debug(f"Skipping Neo4j auto-registration: {e}")
