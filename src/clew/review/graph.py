"""
Impact radius analysis via graph queries.

Given a changed file, finds reverse dependencies: files that import
modules defined in it, or call functions defined in it.

Supports both Neo4j and LadybugDB backends via the adapter system.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..config import get_config

logger = logging.getLogger("clew.review.graph")

_CRITICAL_PATTERNS = ("auth", "payment", "billing", "security", "core", "main")


@dataclass(slots=True)
class ImpactedFile:
    path: str
    relationship: str
    score: float = 0.0
    co_changed: bool = False  # True if this consumer is also in the current diff
    co_deleted: bool = False  # True if this consumer is deleted in the current diff

    def apply_criticality_boost(self, patterns: Sequence[str] = _CRITICAL_PATTERNS) -> None:
        lowered = self.path.lower()
        if any(p in lowered for p in patterns):
            self.score += 5.0


def _get_graph_backend():
    """Get the appropriate graph backend based on config.

    Returns a tuple of (backend_type, backend) where:
    - ("ladybug", LadybugUnifiedStore) for embedded mode
    - ("neo4j", neo4j.Driver) for server mode
    """
    cfg = get_config()
    if cfg.server.graph_adapter == "ladybug":
        from ..stores import _get_ladybug_store

        return "ladybug", _get_ladybug_store(cfg)

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        cfg.store.neo4j_uri,
        auth=(cfg.store.neo4j_user, cfg.store.neo4j_password),
    )
    return "neo4j", driver


def _derive_repo_id(file_path: str) -> str | None:
    """Try to derive repo_id from the cwd git remote."""
    import re

    try:
        import git

        repo = git.Repo(".", search_parent_directories=True)
        for remote in repo.remotes:
            url = re.sub(r"\.git$", "", remote.url)
            match = re.search(r"[:/]([^/:]+/[^/:]+)$", url)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def _file_stem_variants(file_path: str) -> list[str]:
    """Generate module name variants from a file path for import matching.

    E.g. ``crates/monastic-lectionary/src/trappist.rs`` produces:
    ``["trappist", "trappist::"]``
    so we can match imports like ``trappist::TrappistLectionary``.
    """
    stem = PurePosixPath(file_path).stem
    if stem in ("mod", "lib", "main"):
        # For mod.rs / lib.rs, use parent directory name
        stem = PurePosixPath(file_path).parent.name
    return [stem]


async def get_impact_radius(
    client,  # ClewAPIClient — unused now but kept for interface compat
    file_path: str,
    limit: int = 10,
    repo_id: str | None = None,
    changed_files: set[str] | None = None,
    deleted_files: set[str] | None = None,
) -> list[ImpactedFile]:
    """Find files that depend on *file_path* via graph query.

    Supports both Neo4j and LadybugDB backends.

    Checks three relationship types:
    1. IMPORTS — files importing modules whose name matches the changed file's stem
    2. CALLS — files calling functions defined in the changed file
    3. DEFINES consumers — files that import CodeBlocks defined in the changed file

    If *changed_files* is provided, consumers that are also in the diff
    are marked ``co_changed=True`` so the LLM can account for coordinated
    changes.
    """
    repo_id = repo_id or _derive_repo_id(file_path)
    if not repo_id:
        logger.warning("Could not determine repo_id for impact analysis")
        return []

    backend_type, backend = _get_graph_backend()
    try:
        if backend_type == "ladybug":
            impacted = _query_consumers_ladybug(backend, repo_id, file_path)
        else:
            impacted = _query_consumers_neo4j(backend, repo_id, file_path)
        results = _annotate_and_rank(
            impacted,
            changed_files or set(),
            deleted_files or set(),
            limit,
        )
        logger.info(
            "Impact analysis for %s: found %d consumers (%d co-changed)",
            file_path,
            len(results),
            sum(1 for f in results if f.co_changed),
        )
        return results
    finally:
        if backend_type == "neo4j":
            backend.close()


def _add_hit(impacted: dict[str, ImpactedFile], path: str, rel: str, score: float) -> None:
    """Record or update a consumer hit."""
    if path not in impacted:
        impacted[path] = ImpactedFile(path=path, relationship=rel)
    impacted[path].score += score


def _query_consumers_neo4j(driver, repo_id: str, file_path: str) -> dict[str, ImpactedFile]:
    """Run three Cypher queries against Neo4j to find reverse dependencies."""
    impacted: dict[str, ImpactedFile] = {}
    stems = _file_stem_variants(file_path)

    with driver.session() as session:
        # 1. Module-stem imports
        for stem in stems:
            for rec in session.run(
                """
                MATCH (f:File {repo_id: $repo_id})-[:IMPORTS]->(m:Module {repo_id: $repo_id})
                WHERE m.name STARTS WITH $stem AND f.path <> $path
                RETURN DISTINCT f.path AS path
                """,
                repo_id=repo_id,
                stem=stem,
                path=file_path,
            ):
                _add_hit(impacted, rec["path"], "IMPORTS", 1.0)

        # 2. Function callers
        for rec in session.run(
            """
            MATCH (:File {repo_id: $repo_id, path: $path})-[:DEFINES]->(cb:CodeBlock)
            WITH cb.name AS def_name
            MATCH (caller:File {repo_id: $repo_id})-[:CALLS]->(fn:Function {name: def_name, repo_id: $repo_id})
            WHERE caller.path <> $path
            RETURN DISTINCT caller.path AS path
            """,
            repo_id=repo_id,
            path=file_path,
        ):
            _add_hit(impacted, rec["path"], "CALLS", 1.0)

        # 3. Symbol imports (Rust `use crate::module::Symbol`)
        for rec in session.run(
            """
            MATCH (:File {repo_id: $repo_id, path: $path})-[:DEFINES]->(cb:CodeBlock)
            WITH cb.name AS def_name
            MATCH (imp:File {repo_id: $repo_id})-[:IMPORTS]->(m:Module {repo_id: $repo_id})
            WHERE m.name ENDS WITH def_name AND imp.path <> $path
            RETURN DISTINCT imp.path AS path
            """,
            repo_id=repo_id,
            path=file_path,
        ):
            _add_hit(impacted, rec["path"], "IMPORTS", 0.5)

    return impacted


def _query_consumers_ladybug(store, repo_id: str, file_path: str) -> dict[str, ImpactedFile]:
    """Run three Cypher queries against LadybugDB to find reverse dependencies.

    Uses explicit relationship table names required by LadybugDB.
    """
    impacted: dict[str, ImpactedFile] = {}
    stems = _file_stem_variants(file_path)
    conn = store._conn

    # 1. Module-stem imports
    for stem in stems:
        rows = conn.execute(
            """
            MATCH (f:File)-[:File_IMPORTS_Module]->(m:Module)
            WHERE f.repo_id = $repo_id AND m.repo_id = $repo_id
              AND m.name STARTS WITH $stem AND f.path <> $path
            RETURN DISTINCT f.path AS path
            """,
            parameters={"repo_id": repo_id, "stem": stem, "path": file_path},
        ).get_all()
        for row in rows:
            if row[0]:
                _add_hit(impacted, row[0], "IMPORTS", 1.0)

    # 2. Function callers
    rows = conn.execute(
        """
        MATCH (src:File {repo_id: $repo_id, path: $path})-[:File_DEFINES_CodeBlock]->(cb:CodeBlock)
        WITH cb.name AS def_name
        MATCH (caller:File)-[:File_CALLS_Function]->(fn:Function {name: def_name, repo_id: $repo_id})
        WHERE caller.repo_id = $repo_id AND caller.path <> $path
        RETURN DISTINCT caller.path AS path
        """,
        parameters={"repo_id": repo_id, "path": file_path},
    ).get_all()
    for row in rows:
        if row[0]:
            _add_hit(impacted, row[0], "CALLS", 1.0)

    # 3. Symbol imports
    rows = conn.execute(
        """
        MATCH (src:File {repo_id: $repo_id, path: $path})-[:File_DEFINES_CodeBlock]->(cb:CodeBlock)
        WITH cb.name AS def_name
        MATCH (imp:File)-[:File_IMPORTS_Module]->(m:Module)
        WHERE imp.repo_id = $repo_id AND m.repo_id = $repo_id
          AND m.name ENDS WITH def_name AND imp.path <> $path
        RETURN DISTINCT imp.path AS path
        """,
        parameters={"repo_id": repo_id, "path": file_path},
    ).get_all()
    for row in rows:
        if row[0]:
            _add_hit(impacted, row[0], "IMPORTS", 0.5)

    return impacted


def _annotate_and_rank(
    impacted: dict[str, ImpactedFile],
    changed: set[str],
    deleted: set[str],
    limit: int,
) -> list[ImpactedFile]:
    """Apply co-change/co-delete flags, boost criticality, sort, and truncate."""
    results = list(impacted.values())
    for f in results:
        f.co_changed = f.path in changed
        f.co_deleted = f.path in deleted
        f.apply_criticality_boost()
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]
