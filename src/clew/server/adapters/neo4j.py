"""
Neo4j Graph Store Adapter

Implements the GraphStore protocol for Neo4j.
"""

import logging
from contextlib import contextmanager
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

from .base import GraphEdge, GraphNode, GraphResult, GraphStats, PRData

logger = logging.getLogger("clew.adapters.neo4j")

# Exceptions that indicate Neo4j connectivity / auth issues
_NEO4J_ERRORS = (Neo4jError, ServiceUnavailable, AuthError)

# Allowed relationship types for traversal (Cypher-injection safeguard)
_ALLOWED_REL_TYPES = {"IMPORTS", "CALLS", "CONTAINS", "DEFINES"}


def _dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    """Return edges deduplicated by id."""
    return list({e.id: e for e in edges}.values())


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

    @contextmanager
    def _session_run(self, operation: str):
        """Context manager that runs a Neo4j session and logs errors consistently."""
        try:
            with self.driver.session() as session:
                yield session
        except _NEO4J_ERRORS as e:
            logger.error(f"Neo4j {operation} failed: {e}", exc_info=True)
            raise

    def _build_traverse_query(self, repo_id: str | None, depth: int) -> str:
        """Build the Cypher traversal query."""
        if repo_id:
            source_match = "(source {path: $start_node_id, repo_id: $repo_id})"
        else:
            source_match = "(source {path: $start_node_id})"

        return f"""
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
        filtered_types = self._sanitize_rel_types(relationship_types)
        depth = max(1, min(depth, 3))
        query = self._build_traverse_query(repo_id, depth)

        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        with self._session_run("traversal") as session:
            result = session.run(query, start_node_id=start_id, rel_types=filtered_types, repo_id=repo_id)  # type: ignore[arg-type]
            for record in result:
                source_path = record["source_path"] or "unknown"
                target_path = record["target_path"] or "unknown"

                if source_path not in nodes:
                    nodes[source_path] = self._parse_node(record, "source")
                if target_path not in nodes:
                    nodes[target_path] = self._parse_node(record, "target")

                edges.append(self._parse_edge(record, source_path, target_path))

        return GraphResult(nodes=list(nodes.values()), edges=_dedupe_edges(edges))

    @staticmethod
    def _sanitize_rel_types(relationship_types: list[str] | None) -> list[str]:
        """Validate and filter relationship types against the allow-list."""
        if relationship_types is None:
            return list(_ALLOWED_REL_TYPES)
        filtered = [t for t in relationship_types if t in _ALLOWED_REL_TYPES]
        if not filtered:
            logger.warning("No valid relationship types provided, defaulting to all allowed types")
            return list(_ALLOWED_REL_TYPES)
        return filtered

    def _parse_node(self, record, prefix: str) -> GraphNode:
        """Parse a node from a Neo4j record using column-name prefix."""
        return GraphNode(
            id=record[f"{prefix}_path"] or "unknown",
            label=record[f"{prefix}_label"] or "Unknown",
            properties=dict(record[f"{prefix}_props"]) if record[f"{prefix}_props"] else {},
        )

    def _parse_edge(self, record, source_id: str, target_id: str) -> GraphEdge:
        """Parse an edge from a Neo4j record."""
        return GraphEdge(
            id=record["rel_id"],
            source=source_id,
            target=target_id,
            type=record["rel_type"],
            properties=dict(record["rel_props"]) if record["rel_props"] else {},
        )

    @staticmethod
    def _get_element_id(entity) -> str:
        """Get element_id from node or relationship, falling back to id."""
        val = getattr(entity, "element_id", None)
        return val if val is not None else str(entity.id)

    def _collect_entity_node(self, entity, label: str, nodes: dict[str, GraphNode]) -> str | None:
        """Add a graph entity as a GraphNode if not already seen. Returns its id."""
        if entity is None:
            return None
        eid = self._get_element_id(entity)
        if eid not in nodes:
            if hasattr(entity, "labels") and entity.labels:
                label = list(entity.labels)[0]
            nodes[eid] = GraphNode(id=eid, label=label, properties=dict(entity))
        return eid

    def _collect_relationship_edge(
        self, rel, source_id: str | None, target_id: str | None, rel_type: str, edges: list[GraphEdge]
    ) -> None:
        """Append a GraphEdge for a Neo4j relationship if all parts are present."""
        if rel is None or source_id is None or target_id is None:
            return
        edges.append(
            GraphEdge(
                id=self._get_element_id(rel),
                source=source_id,
                target=target_id,
                type=rel_type,
                properties=dict(rel),
            )
        )

    # ------------------------------------------------------------------
    # PR operations
    # ------------------------------------------------------------------

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
        _defaults = ("title", "url", "state", "author", "created_at", "base_branch", "head_branch")
        params = {k: pr_data.get(k, "") for k in _defaults}  # type: ignore[arg-type]
        params["number"] = pr_data.get("number")  # type: ignore[assignment]
        params["repo_id"] = pr_data.get("repo_id")  # type: ignore[assignment]

        with self._session_run("create_pr_node") as session:
            record = session.run(query, **params).single()
            return record["id"] if record else ""

    async def link_pr_to_files(self, pr_number: int, repo_id: str, file_paths: list[str]) -> None:
        """Link PR to files."""
        query = """
        MATCH (pr:PullRequest {number: $number, repo_id: $repo_id})
        UNWIND $file_paths AS file_path
        MATCH (f:File {path: file_path, repo_id: $repo_id})
        MERGE (pr)-[:MODIFIES]->(f)
        """
        with self._session_run("link_pr_to_files") as session:
            session.run(query, number=pr_number, repo_id=repo_id, file_paths=file_paths)

    async def get_file_pull_requests(self, file_path: str, repo_id: str | None = None) -> list[GraphNode]:
        """Get PRs for a file."""
        repo_clause = ", repo_id: $repo_id" if repo_id else ""
        query = f"""
        MATCH (pr:PullRequest)-[:MODIFIES]->(f:File {{path: $file_path{repo_clause}}})
        RETURN pr
        LIMIT 50
        """
        with self._session_run("get_file_pull_requests") as session:
            result = session.run(query, file_path=file_path, repo_id=repo_id)
            return [
                GraphNode(id=self._get_element_id(r["pr"]), label="PullRequest", properties=dict(r["pr"]))
                for r in result
            ]

    def _parse_pr_impact_record(self, record, nodes: dict[str, GraphNode], edges: list[GraphEdge]) -> None:
        """Parse nodes and edges from a PR impact record."""
        pr_id = self._collect_entity_node(record["pr"], "PullRequest", nodes)
        f_id = self._collect_entity_node(record["f"], "File", nodes)
        c_id = self._collect_entity_node(record["c"], "CodeBlock", nodes)

        self._collect_relationship_edge(record["r1"], pr_id, f_id, "MODIFIES", edges)
        self._collect_relationship_edge(record["r2"], f_id, c_id, "DEFINES", edges)

    async def get_pr_impact(self, pr_number: int, repo_id: str) -> GraphResult:
        """Get impact of a PR."""
        query = """
        MATCH (pr:PullRequest {number: $number, repo_id: $repo_id})
        MATCH (pr)-[r1:MODIFIES]->(f:File)
        OPTIONAL MATCH (f)-[r2:DEFINES]->(c:CodeBlock)
        RETURN f, r1, pr, r2, c
        LIMIT 100
        """
        with self._session_run("get_pr_impact") as session:
            result = session.run(query, number=pr_number, repo_id=repo_id)
            nodes: dict[str, GraphNode] = {}
            edges: list[GraphEdge] = []
            for record in result:
                self._parse_pr_impact_record(record, nodes, edges)
            return GraphResult(nodes=list(nodes.values()), edges=_dedupe_edges(edges))

    # ------------------------------------------------------------------
    # Neighbor / stats / policy operations
    # ------------------------------------------------------------------

    async def get_neighbors_batch(self, paths: list[str], repo_id: str | None = None) -> dict[str, list[str]]:
        """Return {path: [neighbor_paths]} for all given paths in one Cypher query."""
        if not paths:
            return {}

        repo_clause = ", repo_id: $repo_id" if repo_id else ""
        query = f"""
        UNWIND $paths AS p
        MATCH (f:File {{path: p{repo_clause}}})
              -[:IMPORTS|CALLS]->(mid)
              <-[:IMPORTS|CALLS|DEFINES]-(neighbor:File)
        WHERE neighbor.path <> p
        RETURN p AS source, collect(DISTINCT neighbor.path) AS neighbors
        """
        result_map: dict[str, list[str]] = {p: [] for p in paths}
        try:
            with self.driver.session() as session:
                for record in session.run(query, paths=paths, repo_id=repo_id):
                    result_map[record["source"]] = record["neighbors"]
        except _NEO4J_ERRORS as e:
            logger.error(f"Neo4j get_neighbors_batch failed: {e}", exc_info=True)
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
                node_count = (session.run(query_nodes, **params).single() or {"count": 0})["count"]
                edge_count = (session.run(query_edges, **params).single() or {"count": 0})["count"]
                density = edge_count / (node_count * (node_count - 1)) if node_count > 1 else 0.0
                return {"node_count": node_count, "edge_count": edge_count, "density": round(density, 6)}
        except _NEO4J_ERRORS as e:
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
        with self._session_run("create_policy") as session:
            record = session.run(
                query,
                id=policy["id"],
                type=policy["type"],
                pattern=policy["pattern"],
                severity=policy["severity"],
                message=policy["message"],
                precept_id=policy.get("precept_id"),
            ).single()
            return record["id"] if record else policy["id"]

    async def get_policies(self) -> list[dict[str, Any]]:
        """Return all active PolicyRule nodes."""
        query = """
        MATCH (p:PolicyRule)
        RETURN p.id AS id, p.type AS type, p.pattern AS pattern,
               p.severity AS severity, p.message AS message,
               p.precept_id AS precept_id
        ORDER BY p.id
        """
        with self._session_run("get_policies") as session:
            return [dict(record) for record in session.run(query)]

    async def delete_policy(self, policy_id: str) -> bool:
        """Delete a PolicyRule node by ID."""
        query = """
        MATCH (p:PolicyRule {id: $id})
        DELETE p
        RETURN count(*) AS deleted
        """
        with self._session_run("delete_policy") as session:
            record = session.run(query, id=policy_id).single()
            return bool(record and record["deleted"] > 0)


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
