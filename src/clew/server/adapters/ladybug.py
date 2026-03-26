"""
LadybugDB Unified Store Adapter

Implements GraphStore + VectorStore protocols (query-side) and
GraphWriter + VectorWriter protocols (ingestion-side) against a
single embedded LadybugDB database directory.

No external servers required — the entire storage layer is a
directory on disk.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from .base import (
    GraphEdge,
    GraphNode,
    GraphResult,
    GraphStats,
    PRData,
    SearchResult,
)

logger = logging.getLogger("clew.adapters.ladybug")

_ALLOWED_REL_TYPES = {"IMPORTS", "CALLS", "CONTAINS", "DEFINES"}

# Shared instance cache: one LadybugUnifiedStore per resolved DB path
_instances: dict[str, LadybugUnifiedStore] = {}

SCHEMA_VERSION = "1"


def _make_id(*parts: str) -> str:
    """Create a deterministic 16-char hex ID from parts."""
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:16]


# Map logical relationship types to concrete LadybugDB rel table names
_REL_TABLE_MAP: dict[str, list[str]] = {
    "IMPORTS": ["File_IMPORTS_Module", "Module_IMPORTS_Module"],
    "CALLS": ["File_CALLS_Function", "Function_CALLS_Function"],
    "DEFINES": ["File_DEFINES_CodeBlock", "File_DEFINES_Function"],
    "CONTAINS": ["Repository_CONTAINS_File"],
}


class LadybugUnifiedStore:
    """
    Unified graph + vector store backed by an embedded LadybugDB database.

    Implements all four storage protocols:
    - GraphStore (query-side): traverse, get_stats, get_neighbors_batch, etc.
    - VectorStore (query-side): search, upsert
    - GraphWriter (ingestion-side): create_repo_node, create_file_node, etc.
    - VectorWriter (ingestion-side): add, add_batch, flush, delete, etc.
    """

    def __init__(self, path: str, embedding_dimension: int = 1536, embedding_provider: Any = None):
        import real_ladybug as lb

        self._path = path
        self._dimension = embedding_dimension
        self._embedding_provider = embedding_provider
        self._db = lb.Database(path)
        self._conn = lb.Connection(self._db)

        self.ensure_schema()

    @classmethod
    def get_or_create(
        cls, path: str, embedding_dimension: int = 1536, embedding_provider: Any = None
    ) -> LadybugUnifiedStore:
        """Get or create a shared instance for the given database path."""
        if path not in _instances:
            _instances[path] = cls(path, embedding_dimension, embedding_provider)
        instance = _instances[path]
        # Update embedding provider if provided (may be set after initial creation)
        if embedding_provider is not None:
            instance._embedding_provider = embedding_provider
        return instance

    def close(self) -> None:
        """Close the database connection."""
        _instances.pop(self._path, None)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Create all node tables, relationship tables, and vector indices."""
        dim = self._dimension
        conn = self._conn

        # Metadata table
        conn.execute("CREATE NODE TABLE IF NOT EXISTS _metadata (key STRING, value STRING, PRIMARY KEY (key))")

        # Check dimension compatibility
        result = conn.execute("MATCH (m:_metadata {key: 'embedding_dimension'}) RETURN m.value AS dim")
        rows = result.get_all()
        if rows:
            stored_dim = int(rows[0][0])
            if stored_dim != dim:
                raise ValueError(
                    f"Embedding dimension mismatch (configured: {dim}, database: {stored_dim}). "
                    f"Re-index required: clewso index --force <repo>"
                )
        else:
            conn.execute(
                "CREATE (m:_metadata {key: 'embedding_dimension', value: $val})",
                parameters={"val": str(dim)},
            )
            conn.execute(
                "CREATE (m:_metadata {key: 'schema_version', value: $val})",
                parameters={"val": SCHEMA_VERSION},
            )

        # Node tables
        conn.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS File (
                id STRING, path STRING, repo_id STRING, language STRING,
                last_indexed_at STRING, embedding FLOAT[{dim}],
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Module (
                id STRING, name STRING, repo_id STRING,
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Function (
                id STRING, name STRING, repo_id STRING, file_path STRING,
                PRIMARY KEY (id)
            )
        """)
        conn.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS CodeBlock (
                id STRING, name STRING, type STRING, file_path STRING,
                repo_id STRING, start_line INT64, end_line INT64,
                text STRING, embedding FLOAT[{dim}],
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Repository (
                id STRING, name STRING, url STRING, last_indexed_commit STRING,
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS PullRequest (
                id STRING, number INT64, repo_id STRING, title STRING,
                url STRING, state STRING, author STRING,
                PRIMARY KEY (id)
            )
        """)
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS PolicyRule (
                id STRING, type STRING, pattern STRING,
                severity STRING, message STRING, precept_id STRING,
                PRIMARY KEY (id)
            )
        """)

        # Relationship tables
        conn.execute("CREATE REL TABLE IF NOT EXISTS File_IMPORTS_Module (FROM File TO Module)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS Module_IMPORTS_Module (FROM Module TO Module)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS File_CALLS_Function (FROM File TO Function)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS Function_CALLS_Function (FROM Function TO Function)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS File_DEFINES_CodeBlock (FROM File TO CodeBlock)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS File_DEFINES_Function (FROM File TO Function)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS Repository_CONTAINS_File (FROM Repository TO File)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS PullRequest_MODIFIES_File (FROM PullRequest TO File)")

        # Vector indices
        for table, idx_name in [("CodeBlock", "codeblock_embedding_idx"), ("File", "file_embedding_idx")]:
            try:
                conn.execute(f"""
                    CALL CREATE_VECTOR_INDEX(
                        '{table}', '{idx_name}', 'embedding',
                        metric := 'cosine', mu := 30, ml := 60, efc := 200
                    )
                """)
            except Exception:
                pass  # Index already exists

        logger.info("LadybugDB schema ensured at %s", self._path)

    # ------------------------------------------------------------------
    # GraphStore protocol — traverse
    # ------------------------------------------------------------------

    async def traverse(
        self, start_id: str, depth: int = 2, relationship_types: list[str] | None = None, repo_id: str | None = None
    ) -> GraphResult:
        """Traverse the graph from a starting node (matched by path)."""
        filtered_types = self._sanitize_rel_types(relationship_types)
        depth = max(1, min(depth, 3))

        # Build UNION queries across concrete rel tables for requested types
        rel_tables = []
        for rt in filtered_types:
            rel_tables.extend(_REL_TABLE_MAP.get(rt, []))

        if not rel_tables:
            return GraphResult(nodes=[], edges=[])

        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        # Query outgoing and incoming edges separately to preserve direction
        for rel_table in rel_tables:
            rel_type = rel_table.split("_")[1]  # e.g., "IMPORTS" from "File_IMPORTS_Module"
            repo_filter = " AND src.repo_id = $repo_id" if repo_id else ""

            # Outgoing: start_id -> target (up to `depth` hops)
            out_query = f"""
                MATCH (src {{path: $start_id{repo_filter}}})-[:{rel_table}*1..{depth}]->(tgt)
                RETURN DISTINCT
                    COALESCE(src.path, src.name, src.id) AS source_path,
                    label(src) AS source_label,
                    COALESCE(tgt.path, tgt.name, tgt.id) AS target_path,
                    label(tgt) AS target_label
                LIMIT 50
            """
            # Incoming: source -> start_id (up to `depth` hops)
            in_query = f"""
                MATCH (src)-[:{rel_table}*1..{depth}]->(tgt {{path: $start_id{repo_filter.replace("src.", "tgt.")}}})
                RETURN DISTINCT
                    COALESCE(src.path, src.name, src.id) AS source_path,
                    label(src) AS source_label,
                    COALESCE(tgt.path, tgt.name, tgt.id) AS target_path,
                    label(tgt) AS target_label
                LIMIT 50
            """

            for query in (out_query, in_query):
                try:
                    result = self._conn.execute(query, parameters={"start_id": start_id, "repo_id": repo_id})
                    for row in result.get_all():
                        s_path, s_label, t_path, t_label = row
                        s_path = s_path or "unknown"
                        t_path = t_path or "unknown"

                        if s_path not in nodes:
                            nodes[s_path] = GraphNode(id=s_path, label=s_label or "Unknown", properties={})
                        if t_path not in nodes:
                            nodes[t_path] = GraphNode(id=t_path, label=t_label or "Unknown", properties={})

                        edge_id = f"{s_path}-{rel_type}-{t_path}"
                        edges.append(GraphEdge(id=edge_id, source=s_path, target=t_path, type=rel_type, properties={}))
                except Exception as e:
                    logger.debug("Traverse query on %s failed: %s", rel_table, e)

        return GraphResult(nodes=list(nodes.values()), edges=edges)

    @staticmethod
    def _sanitize_rel_types(relationship_types: list[str] | None) -> list[str]:
        if relationship_types is None:
            return list(_ALLOWED_REL_TYPES)
        filtered = [t for t in relationship_types if t in _ALLOWED_REL_TYPES]
        return filtered or list(_ALLOWED_REL_TYPES)

    # ------------------------------------------------------------------
    # GraphStore protocol — stats, neighbors, PR, policy
    # ------------------------------------------------------------------

    async def get_stats(self, repo_id: str | None = None) -> GraphStats:
        try:
            # Count all node types, not just File
            nc = 0
            for table in ("File", "Module", "Function", "CodeBlock", "Repository", "PullRequest", "PolicyRule"):
                try:
                    if repo_id:
                        # Repository uses `id` as repo identifier, others use `repo_id`
                        key = "id" if table == "Repository" else "repo_id"
                        r = self._conn.execute(
                            f"MATCH (n:{table} {{{key}: $rid}}) RETURN count(n) AS c",
                            parameters={"rid": repo_id},
                        ).get_all()
                    else:
                        r = self._conn.execute(f"MATCH (n:{table}) RETURN count(n) AS c").get_all()
                    nc += r[0][0] if r else 0
                except Exception:
                    pass
            # Count edges across all rel tables (scoped by repo_id if provided)
            ec = 0
            for tables in _REL_TABLE_MAP.values():
                for t in tables:
                    try:
                        if repo_id:
                            r = self._conn.execute(
                                f"MATCH (a {{repo_id: $rid}})-[r:{t}]->() RETURN count(r) AS c",
                                parameters={"rid": repo_id},
                            ).get_all()
                        else:
                            r = self._conn.execute(f"MATCH ()-[r:{t}]->() RETURN count(r) AS c").get_all()
                        ec += r[0][0] if r else 0
                    except Exception:
                        pass
            density = ec / (nc * (nc - 1)) if nc > 1 else 0.0
            return {"node_count": nc, "edge_count": ec, "density": round(density, 6)}
        except Exception as e:
            logger.error("LadybugDB get_stats failed: %s", e)
            return {"node_count": 0, "edge_count": 0, "density": 0.0}

    async def get_neighbors_batch(self, paths: list[str], repo_id: str | None = None) -> dict[str, list[str]]:
        if not paths:
            return {}
        result_map: dict[str, list[str]] = {p: [] for p in paths}
        repo_filter = ", repo_id: $repo_id" if repo_id else ""
        for p in paths:
            try:
                neighbors: set[str] = set()
                params: dict[str, Any] = {"path": p}
                if repo_id:
                    params["repo_id"] = repo_id
                for rel_table in ("File_IMPORTS_Module", "File_CALLS_Function"):
                    query = f"""
                        MATCH (f:File {{path: $path{repo_filter}}})-[:{rel_table}]->(mid)
                        <-[:{rel_table}]-(neighbor:File)
                        WHERE neighbor.path <> $path
                        RETURN DISTINCT neighbor.path AS np
                    """
                    rows = self._conn.execute(query, parameters=params).get_all()
                    neighbors.update(row[0] for row in rows if row[0])
                result_map[p] = list(neighbors)
            except Exception as e:
                logger.debug("get_neighbors_batch failed for %s: %s", p, e)
        return result_map

    async def create_pr_node(self, pr_data: PRData) -> str:
        pr_id = _make_id(str(pr_data.get("repo_id", "")), str(pr_data.get("number", "")))
        self._conn.execute(
            """
            MERGE (pr:PullRequest {id: $id})
            SET pr.number = $number, pr.repo_id = $repo_id, pr.title = $title,
                pr.url = $url, pr.state = $state, pr.author = $author
            """,
            parameters={
                "id": pr_id,
                "number": pr_data.get("number", 0),
                "repo_id": pr_data.get("repo_id", ""),
                "title": pr_data.get("title", ""),
                "url": pr_data.get("url", ""),
                "state": pr_data.get("state", ""),
                "author": pr_data.get("author", ""),
            },
        )
        return pr_id

    async def link_pr_to_files(self, pr_number: int, repo_id: str, file_paths: list[str]) -> None:
        pr_id = _make_id(repo_id, str(pr_number))
        for fp in file_paths:
            file_id = _make_id(repo_id, fp)
            try:
                self._conn.execute(
                    """
                    MATCH (pr:PullRequest {id: $pr_id}), (f:File {id: $file_id})
                    MERGE (pr)-[:PullRequest_MODIFIES_File]->(f)
                    """,
                    parameters={"pr_id": pr_id, "file_id": file_id},
                )
            except Exception as e:
                logger.debug("link_pr_to_files failed for %s: %s", fp, e)

    async def get_file_pull_requests(self, file_path: str, repo_id: str | None = None) -> list[GraphNode]:
        params: dict[str, Any] = {"file_path": file_path}
        repo_filter = " AND f.repo_id = $repo_id" if repo_id else ""
        if repo_id:
            params["repo_id"] = repo_id
        query = f"""
            MATCH (pr:PullRequest)-[:PullRequest_MODIFIES_File]->(f:File)
            WHERE f.path = $file_path{repo_filter}
            RETURN pr.id AS id, pr.number AS number, pr.title AS title,
                   pr.repo_id AS repo_id, pr.state AS state, pr.author AS author
            LIMIT 50
        """
        try:
            rows = self._conn.execute(query, parameters=params).get_all()
            return [
                GraphNode(
                    id=row[0] or "",
                    label="PullRequest",
                    properties={
                        "number": row[1],
                        "title": row[2],
                        "repo_id": row[3],
                        "state": row[4],
                        "author": row[5],
                    },
                )
                for row in rows
            ]
        except Exception as e:
            logger.error("get_file_pull_requests failed: %s", e)
            return []

    async def get_pr_impact(self, pr_number: int, repo_id: str) -> GraphResult:
        pr_id = _make_id(repo_id, str(pr_number))
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        try:
            # PR -> File edges
            file_rows = self._conn.execute(
                """
                MATCH (pr:PullRequest {id: $pr_id})-[:PullRequest_MODIFIES_File]->(f:File)
                RETURN pr.id AS pr_id, f.path AS f_path, f.id AS f_id
                """,
                parameters={"pr_id": pr_id},
            ).get_all()
            for row in file_rows:
                pid, fpath, fid = row
                if pid and pid not in nodes:
                    nodes[pid] = GraphNode(id=pid, label="PullRequest", properties={"number": pr_number})
                if fpath and fpath not in nodes:
                    nodes[fpath] = GraphNode(id=fpath, label="File", properties={"path": fpath})
                if pid and fpath:
                    edges.append(
                        GraphEdge(
                            id=f"{pid}-MODIFIES-{fpath}", source=pid, target=fpath, type="MODIFIES", properties={}
                        )
                    )
                # File -> CodeBlock edges
                if fid:
                    try:
                        cb_rows = self._conn.execute(
                            "MATCH (f:File {id: $fid})-[:File_DEFINES_CodeBlock]->(c:CodeBlock) "
                            "RETURN c.name AS name, c.id AS cid, c.type AS ctype",
                            parameters={"fid": fid},
                        ).get_all()
                        for cb_row in cb_rows:
                            cb_name, cb_id, cb_type = cb_row
                            cb_key = cb_id or cb_name or "unknown"
                            if cb_key not in nodes:
                                nodes[cb_key] = GraphNode(
                                    id=cb_key,
                                    label="CodeBlock",
                                    properties={"name": cb_name, "type": cb_type},
                                )
                            edges.append(
                                GraphEdge(
                                    id=f"{fpath}-DEFINES-{cb_key}",
                                    source=fpath,
                                    target=cb_key,
                                    type="DEFINES",
                                    properties={},
                                )
                            )
                    except Exception:
                        pass
        except Exception as e:
            logger.error("get_pr_impact failed: %s", e)
        return GraphResult(nodes=list(nodes.values()), edges=edges)

    async def create_policy(self, policy: dict[str, Any]) -> str:
        self._conn.execute(
            """
            MERGE (p:PolicyRule {id: $id})
            SET p.type = $type, p.pattern = $pattern, p.severity = $severity,
                p.message = $message, p.precept_id = $precept_id
            """,
            parameters={
                "id": policy["id"],
                "type": policy["type"],
                "pattern": policy["pattern"],
                "severity": policy["severity"],
                "message": policy.get("message", ""),
                "precept_id": policy.get("precept_id"),
            },
        )
        return policy["id"]

    async def get_policies(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            MATCH (p:PolicyRule)
            RETURN p.id AS id, p.type AS type, p.pattern AS pattern,
                   p.severity AS severity, p.message AS message,
                   p.precept_id AS precept_id
            ORDER BY p.id
            """
        ).get_all()
        return [
            {"id": r[0], "type": r[1], "pattern": r[2], "severity": r[3], "message": r[4], "precept_id": r[5]}
            for r in rows
        ]

    async def delete_policy(self, policy_id: str) -> bool:
        result = self._conn.execute(
            "MATCH (p:PolicyRule {id: $id}) DELETE p RETURN count(*) AS deleted",
            parameters={"id": policy_id},
        ).get_all()
        return bool(result and result[0][0] > 0)

    # ------------------------------------------------------------------
    # VectorStore protocol — search, upsert
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_filters(
        repo_id: str | None, file_path: str | None, node_type: str | None, repo: str | None, filters: Any | None
    ) -> bool:
        """Return True if a result row passes all active filters."""
        if repo and repo_id != repo:
            return False
        if not filters:
            return True
        if filters.get("path") and file_path != filters["path"]:
            return False
        if filters.get("path_contains") and filters["path_contains"] not in (file_path or ""):
            return False
        if filters.get("type") and node_type != filters["type"]:
            return False
        return True

    @staticmethod
    def _row_to_search_result(row: tuple) -> SearchResult:
        """Convert a raw vector query row to a SearchResult."""
        node_id, name, file_path, repo_id, node_type, text, distance = row
        return SearchResult(
            id=node_id or "",
            score=max(0.0, 1.0 - (distance or 0.0)),
            content=text or "",
            metadata={
                "path": file_path or "",
                "repo_id": repo_id or "",
                "name": name or "",
                "type": node_type or "",
                "text": text or "",
            },
        )

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        repo: str | None = None,
        filters: Any | None = None,
    ) -> list[SearchResult]:
        """Search using LadybugDB's native vector index."""
        has_filters = repo or (filters and any(filters.get(k) for k in ("path", "path_contains", "type")))
        fetch_limit = limit * 3 if has_filters else limit

        try:
            rows = self._conn.execute(
                """
                CALL QUERY_VECTOR_INDEX('CodeBlock', 'codeblock_embedding_idx', $vec, $lim)
                RETURN node.id AS id, node.name AS name, node.file_path AS file_path,
                       node.repo_id AS repo_id, node.type AS type, node.text AS text,
                       distance
                ORDER BY distance
                """,
                parameters={"vec": query_vector, "lim": fetch_limit},
            ).get_all()
        except Exception as e:
            logger.error("LadybugDB vector search failed: %s", e)
            return []

        results = []
        for row in rows:
            if not self._matches_filters(row[3], row[2], row[4], repo, filters):
                continue
            results.append(self._row_to_search_result(row))
            if len(results) >= limit:
                break
        return results

    async def upsert(self, id: str, content: str, vector: list[float], metadata: Any | None = None) -> None:
        meta = metadata or {}
        cb_id = id or _make_id(
            meta.get("repo_id", ""), meta.get("path", ""), meta.get("name", ""), meta.get("type", "")
        )
        self._conn.execute(
            """
            MERGE (c:CodeBlock {id: $id})
            SET c.name = $name, c.type = $type, c.file_path = $path,
                c.repo_id = $repo_id, c.text = $text, c.embedding = $vec
            """,
            parameters={
                "id": cb_id,
                "name": meta.get("name", ""),
                "type": meta.get("type", ""),
                "path": meta.get("path", ""),
                "repo_id": meta.get("repo_id", ""),
                "text": content,
                "vec": vector,
            },
        )

    # ------------------------------------------------------------------
    # GraphWriter protocol — ingestion writes
    # ------------------------------------------------------------------

    def create_repo_node(self, repo_id: str, name: str, url: str) -> None:
        self._conn.execute(
            "MERGE (r:Repository {id: $id}) SET r.name = $name, r.url = $url",
            parameters={"id": repo_id, "name": name, "url": url},
        )

    def create_file_node(self, repo_id: str, file_path: str, qdrant_id: str) -> None:
        file_id = _make_id(repo_id, file_path)
        self._conn.execute(
            """
            MERGE (f:File {id: $id})
            SET f.path = $path, f.repo_id = $repo_id
            """,
            parameters={"id": file_id, "path": file_path, "repo_id": repo_id},
        )
        # Link to repository
        try:
            self._conn.execute(
                """
                MATCH (r:Repository {id: $repo_id}), (f:File {id: $file_id})
                MERGE (r)-[:Repository_CONTAINS_File]->(f)
                """,
                parameters={"repo_id": repo_id, "file_id": file_id},
            )
        except Exception as e:
            logger.debug("Failed to link file to repo: %s", e)

    def create_file_nodes_batch(self, repo_id: str, items: list[dict[str, Any]]) -> None:
        for item in items:
            self.create_file_node(repo_id, item["file_path"], item.get("qdrant_id", ""))

    def create_code_node(
        self,
        repo_id: str,
        file_path: str,
        name: str,
        node_type: str,
        start_line: int,
        end_line: int,
        qdrant_id: str,
    ) -> None:
        cb_id = qdrant_id or _make_id(repo_id, file_path, name, node_type)
        file_id = _make_id(repo_id, file_path)
        self._conn.execute(
            """
            MERGE (c:CodeBlock {id: $id})
            SET c.name = $name, c.type = $type, c.file_path = $path,
                c.repo_id = $repo_id, c.start_line = $sl, c.end_line = $el
            """,
            parameters={
                "id": cb_id,
                "name": name,
                "type": node_type,
                "path": file_path,
                "repo_id": repo_id,
                "sl": start_line,
                "el": end_line,
            },
        )
        # DEFINES edge
        try:
            self._conn.execute(
                """
                MATCH (f:File {id: $file_id}), (c:CodeBlock {id: $cb_id})
                MERGE (f)-[:File_DEFINES_CodeBlock]->(c)
                """,
                parameters={"file_id": file_id, "cb_id": cb_id},
            )
        except Exception as e:
            logger.debug("Failed to create DEFINES edge: %s", e)

    def create_import_relationship(self, repo_id: str, file_path: str, module_name: str) -> None:
        file_id = _make_id(repo_id, file_path)
        mod_id = _make_id(repo_id, module_name)
        self._conn.execute(
            "MERGE (m:Module {id: $id}) SET m.name = $name, m.repo_id = $repo_id",
            parameters={"id": mod_id, "name": module_name, "repo_id": repo_id},
        )
        try:
            self._conn.execute(
                """
                MATCH (f:File {id: $file_id}), (m:Module {id: $mod_id})
                MERGE (f)-[:File_IMPORTS_Module]->(m)
                """,
                parameters={"file_id": file_id, "mod_id": mod_id},
            )
        except Exception as e:
            logger.debug("Failed to create IMPORTS edge: %s", e)

    def create_call_relationship(self, repo_id: str, file_path: str, target_name: str) -> None:
        file_id = _make_id(repo_id, file_path)
        func_id = _make_id(repo_id, target_name)
        self._conn.execute(
            "MERGE (fn:Function {id: $id}) SET fn.name = $name, fn.repo_id = $repo_id",
            parameters={"id": func_id, "name": target_name, "repo_id": repo_id},
        )
        try:
            self._conn.execute(
                """
                MATCH (f:File {id: $file_id}), (fn:Function {id: $func_id})
                MERGE (f)-[:File_CALLS_Function]->(fn)
                """,
                parameters={"file_id": file_id, "func_id": func_id},
            )
        except Exception as e:
            logger.debug("Failed to create CALLS edge: %s", e)

    def delete_file_node(self, repo_id: str, file_path: str) -> int:
        file_id = _make_id(repo_id, file_path)
        try:
            # Delete code blocks first
            self._conn.execute(
                "MATCH (f:File {id: $fid})-[:File_DEFINES_CodeBlock]->(c:CodeBlock) DETACH DELETE c",
                parameters={"fid": file_id},
            )
            self._conn.execute(
                "MATCH (f:File {id: $fid})-[:File_DEFINES_Function]->(fn:Function) DETACH DELETE fn",
                parameters={"fid": file_id},
            )
            self._conn.execute("MATCH (f:File {id: $fid}) DETACH DELETE f", parameters={"fid": file_id})
            return 1
        except Exception as e:
            logger.error("delete_file_node failed: %s", e)
            return 0

    def delete_file_edges(self, repo_id: str, file_path: str) -> None:
        file_id = _make_id(repo_id, file_path)
        for rel_table in ("File_IMPORTS_Module", "File_CALLS_Function"):
            try:
                self._conn.execute(
                    f"MATCH (f:File {{id: $fid}})-[r:{rel_table}]->() DELETE r",
                    parameters={"fid": file_id},
                )
            except Exception as e:
                logger.debug("delete_file_edges on %s failed: %s", rel_table, e)

    def delete_files_batch(self, repo_id: str, file_paths: list[str]) -> int:
        count = 0
        for fp in file_paths:
            count += self.delete_file_node(repo_id, fp)
        return count

    def execute_batch(self, operations: list[tuple[str, dict[str, Any]]]) -> None:
        """Execute batch operations, translating Neo4j Cypher to LadybugDB dialect.

        The ingestion pipeline generates Neo4j-style Cypher (schema-optional, implicit
        rel types). This method intercepts those queries and routes them through the
        adapter's typed methods instead.
        """
        if not operations:
            return
        for query, params in operations:
            self._execute_translated(query, params)
        logger.debug("Executed batch of %d operations", len(operations))

    def _execute_translated(self, query: str, params: dict[str, Any]) -> None:
        """Route a Neo4j-style Cypher query to the appropriate typed method."""
        q = query.strip().upper()
        p = params

        # CodeBlock MERGE → create_code_node
        if "MERGE (C:CODEBLOCK" in q or "MERGE (c:CodeBlock" in query:
            self.create_code_node(
                repo_id=p.get("repo_id", ""),
                file_path=p.get("file_path", ""),
                name=p.get("name", ""),
                node_type=p.get("node_type", ""),
                start_line=p.get("start_line", 0),
                end_line=p.get("end_line", 0),
                qdrant_id=p.get("qdrant_id", ""),
            )
            return

        # Module MERGE → create_import_relationship
        if "MERGE (M:MODULE" in q or "MERGE (m:Module" in query:
            self.create_import_relationship(
                repo_id=p.get("repo_id", ""),
                file_path=p.get("file_path", ""),
                module_name=p.get("module_name", ""),
            )
            return

        # Function MERGE → create_call_relationship
        if "MERGE (T:FUNCTION" in q or "MERGE (t:Function" in query:
            self.create_call_relationship(
                repo_id=p.get("repo_id", ""),
                file_path=p.get("file_path", ""),
                target_name=p.get("target_name", ""),
            )
            return

        # Fallback: execute directly — fail loudly if unsupported
        self._conn.execute(query, parameters=params)

    def get_last_indexed_commit(self, repo_id: str) -> str | None:
        rows = self._conn.execute(
            "MATCH (r:Repository {id: $id}) RETURN r.last_indexed_commit AS sha",
            parameters={"id": repo_id},
        ).get_all()
        return rows[0][0] if rows and rows[0][0] else None

    def update_last_indexed_commit(self, repo_id: str, commit_sha: str) -> None:
        self._conn.execute(
            "MATCH (r:Repository {id: $id}) SET r.last_indexed_commit = $sha",
            parameters={"id": repo_id, "sha": commit_sha},
        )

    # ------------------------------------------------------------------
    # VectorWriter protocol — ingestion vector writes
    # ------------------------------------------------------------------

    def _require_embedding_provider(self):
        if not self._embedding_provider:
            raise RuntimeError("No embedding provider configured on LadybugUnifiedStore")
        return self._embedding_provider

    def _write_code_block(self, text: str, metadata: dict[str, Any], embedding: list[float], point_id: str) -> None:
        """Persist a CodeBlock node with its embedding."""
        cb_id = point_id or _make_id(
            metadata.get("repo_id", ""),
            metadata.get("path", ""),
            metadata.get("name", ""),
            metadata.get("type", ""),
        )
        self._conn.execute(
            """
            MERGE (c:CodeBlock {id: $id})
            SET c.name = $name, c.type = $type, c.file_path = $path,
                c.repo_id = $repo_id, c.text = $text, c.embedding = $vec
            """,
            parameters={
                "id": cb_id,
                "name": metadata.get("name", ""),
                "type": metadata.get("type", ""),
                "path": metadata.get("path", ""),
                "repo_id": metadata.get("repo_id", ""),
                "text": text,
                "vec": embedding,
            },
        )

    async def add(self, text: str, metadata: dict[str, Any]) -> str:
        provider = self._require_embedding_provider()
        embedding = await provider.embed(text)
        point_id = str(uuid.uuid4())
        self._write_code_block(text, metadata, embedding, point_id)
        return point_id

    async def add_batch(
        self,
        items: list[tuple[str, dict[str, Any], str | None]],
    ) -> list[str]:
        if not items:
            return []
        provider = self._require_embedding_provider()
        texts = [text for text, _, _ in items]
        embeddings = await provider.embed_batch(texts)

        point_ids: list[str] = []
        for (text, metadata, optional_id), embedding in zip(items, embeddings, strict=True):
            pid = optional_id or str(uuid.uuid4())
            point_ids.append(pid)
            self._write_code_block(text, metadata, embedding, pid)
        return point_ids

    async def flush(self) -> None:
        """No-op — LadybugDB writes are immediate via MERGE."""

    async def delete(self, id: str) -> None:
        try:
            self._conn.execute("MATCH (c:CodeBlock {id: $id}) DETACH DELETE c", parameters={"id": id})
        except Exception as e:
            logger.debug("delete failed for %s: %s", id, e)

    def delete_by_filter(self, repo_id: str, file_path: str) -> int:
        try:
            self._conn.execute(
                "MATCH (c:CodeBlock {repo_id: $rid, file_path: $fp}) DETACH DELETE c",
                parameters={"rid": repo_id, "fp": file_path},
            )
            return 1
        except Exception as e:
            logger.warning("delete_by_filter failed: %s", e)
            return 0


# =============================================================================
# Auto-registration
# =============================================================================


def _register_ladybug():
    """Register LadybugDB adapter with the registry."""
    from . import registry

    def graph_factory() -> LadybugUnifiedStore:
        from clew.config import get_config
        from clew.stores import resolve_ladybug_path

        cfg = get_config()
        path = resolve_ladybug_path(cfg)
        return LadybugUnifiedStore.get_or_create(path, cfg.embeddings.dimension)

    # Same factory for both — shared instance
    registry.graph_store_registry.register("ladybug", graph_factory)
    registry.vector_store_registry.register("ladybug", graph_factory)


try:
    _register_ladybug()
    logger.debug("Registered LadybugDB adapter")
except Exception as e:
    logger.debug("Skipping LadybugDB auto-registration: %s", e)
