"""
Refactored ingestion module using Pipeline architecture.

This module provides a clean, object-oriented interface for ingesting
codebases into vector and graph databases.

The implementation follows SOLID principles and Gang of Four patterns:
- Pipeline Pattern: Composable stages for processing
- Strategy Pattern: Pluggable node processors
- Chain of Responsibility: Sequential stage execution
- Dependency Injection: External dependencies injected
"""

import logging
import os
import re
import sys

import git

from clewso_ingestion.diff import compute_changeset
from clewso_ingestion.embeddings import OllamaEmbeddings, OpenAIEmbeddings
from clewso_ingestion.graph import GraphStore
from clewso_ingestion.incremental_pipeline import IncrementalIngestionPipeline
from clewso_ingestion.parser import CodeParser
from clewso_ingestion.pipeline import IngestionPipeline
from clewso_ingestion.vector import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _build_stores(
    embedding_provider: OpenAIEmbeddings | OllamaEmbeddings,
    sc: dict,
):
    """Build VectorStore and GraphStore from a store_config dict.

    When graph_adapter/vector_adapter is "ladybug", returns a shared
    LadybugUnifiedStore instance that implements both protocols.
    """
    graph_adapter = sc.get("graph_adapter", "ladybug")
    vector_adapter = sc.get("vector_adapter", "ladybug")

    if (graph_adapter == "ladybug") != (vector_adapter == "ladybug"):
        raise ValueError(
            f"Mixed ladybug config not supported for ingestion: "
            f"graph_adapter={graph_adapter}, vector_adapter={vector_adapter}. "
            f"Set both to 'ladybug' or neither."
        )

    if graph_adapter == "ladybug" and vector_adapter == "ladybug":
        # Lazy import to avoid circular dependency (clewso depends on clewso-ingestion)
        # This import works at runtime because both packages are installed together.
        from pathlib import Path

        from clew.server.adapters.ladybug import LadybugUnifiedStore  # type: ignore[import-untyped]

        lb_path = str(Path(sc.get("ladybug_path", "~/.local/share/clewso/graph/")).expanduser())
        Path(lb_path).parent.mkdir(parents=True, exist_ok=True)
        dim = sc.get("embedding_dimension", 1536)
        store = LadybugUnifiedStore.get_or_create(lb_path, dim, embedding_provider)
        return store, store

    vector_store = VectorStore(
        embedding_provider=embedding_provider,
        url=sc.get("qdrant_url") or None,
        api_key=sc.get("qdrant_api_key") or None,
        host=sc.get("qdrant_host") or None,
        port=sc.get("qdrant_port") or None,
        collection=sc.get("qdrant_collection") or None,
    )
    graph_store = GraphStore(
        uri=sc.get("neo4j_uri") or None,
        user=sc.get("neo4j_user") or None,
        password=sc.get("neo4j_password") or None,
    )
    return vector_store, graph_store


def _derive_repo_id(repo_path: str) -> str:
    """Derive a human-readable repo ID from the git remote or directory name.

    Tries ``origin`` remote first (producing e.g. ``owner/repo``), then
    falls back to the directory basename.
    """
    try:
        repo = git.Repo(repo_path)
        for remote in repo.remotes:
            url = remote.url
            # Strip .git suffix and extract owner/repo from SSH or HTTPS URLs
            url = re.sub(r"\.git$", "", url)
            match = re.search(r"[:/]([^/:]+/[^/:]+)$", url)
            if match:
                return match.group(1)
    except Exception:
        pass
    return os.path.basename(os.path.abspath(repo_path))


def _get_embedding_provider() -> OpenAIEmbeddings | OllamaEmbeddings:
    """Initialize an embedding provider (OpenAI first, Ollama fallback)."""
    if os.getenv("OPENAI_API_KEY"):
        try:
            provider = OpenAIEmbeddings()
            logger.info("Using OpenAI embeddings")
            return provider
        except Exception as e:
            logger.warning(f"OpenAI embeddings failed to initialize: {e}")

    try:
        provider = OllamaEmbeddings()
        logger.info("Using Ollama embeddings (local)")
        return provider
    except Exception as e:
        logger.error(f"Failed to initialize any embedding provider: {e}")
        raise RuntimeError("No embedding provider available. Set OPENAI_API_KEY or run Ollama locally.") from e


def _log_and_exit_code(result, label: str = "INGESTION") -> int:
    """Log a ProcessingResult and return the corresponding exit code."""
    logger.info("=" * 60)
    logger.info(f"{label} COMPLETE: {result.message}")
    logger.info(f"Status: {result.status.value}")
    logger.info(f"Items processed: {result.items_processed}")
    logger.info(f"Items failed: {result.items_failed}")

    if result.errors:
        logger.warning(f"Errors encountered: {len(result.errors)}")
        for error in result.errors[:10]:
            logger.warning(f"  - {error['context']}: {error['error']}")
        if len(result.errors) > 10:
            logger.warning(f"  ... and {len(result.errors) - 10} more errors")

    logger.info("=" * 60)

    if result.is_success:
        return 0
    elif result.is_partial:
        logger.warning(f"{label} completed with some errors")
        return 1
    else:
        logger.error(f"{label} failed")
        return 2


def ingest_repo(
    repo_id: str | None,
    repo_path_or_url: str,
    *,
    store_config: dict | None = None,
):
    """
    Ingest a repository into the Clew Engine.

    This is the main entry point for repository ingestion. It:
    1. Initializes database connections (vector and graph stores)
    2. Sets up the code parser
    3. Creates and runs the ingestion pipeline
    4. Handles errors and reports results

    Args:
        repo_id: Unique identifier for the repository
        repo_path_or_url: Local directory path or remote Git repository URL
        store_config: Optional dict of store connection params forwarded to
            VectorStore and GraphStore (keys match StoreConfig field names).
    """
    sc = store_config or {}

    # Use a stable ID if none provided
    if not repo_id:
        repo_id = _derive_repo_id(repo_path_or_url)

    logger.info(f"Initializing ingestion for: {repo_path_or_url} (ID: {repo_id})")

    try:
        embedding_provider = _get_embedding_provider()

        vector_store, graph_store = _build_stores(embedding_provider, sc)
        parser = CodeParser()

        pipeline = IngestionPipeline(vector_store=vector_store, graph_store=graph_store, parser=parser)  # type: ignore[arg-type]

        result = pipeline.run(repo_id, repo_path_or_url)
        return _log_and_exit_code(result)

    except Exception as e:
        logger.error(f"Fatal error during ingestion: {e}", exc_info=True)
        return 3


def ingest_repo_incremental(
    repo_id: str | None,
    repo_path: str,
    *,
    store_config: dict | None = None,
) -> int:
    """Incrementally ingest only files changed since the last indexed commit.

    Looks up the last indexed commit SHA from the graph store.  If no prior
    commit is recorded, falls back to a full ``ingest_repo()`` run.  When
    HEAD already matches the last indexed commit the function short-circuits
    with exit code 0.

    Args:
        repo_id: Unique repository identifier.  When ``None`` a stable hash
            of ``repo_path`` is used.
        repo_path: Local filesystem path to the git repository.
        store_config: Optional dict of store connection params.

    Returns:
        Exit code: 0 = success, 1 = partial, 2 = failed, 3 = fatal.
    """
    sc = store_config or {}

    if not repo_id:
        repo_id = _derive_repo_id(repo_path)

    logger.info(f"Incremental ingestion for: {repo_path} (ID: {repo_id})")

    try:
        embedding_provider = _get_embedding_provider()
        vector_store, graph_store = _build_stores(embedding_provider, sc)
        parser = CodeParser()

        last_sha = graph_store.get_last_indexed_commit(repo_id)

        if last_sha is None:
            logger.info("No prior indexed commit found — falling back to full ingestion")
            return ingest_repo(repo_id, repo_path, store_config=sc)

        # Resolve HEAD
        repo = git.Repo(repo_path)
        head_sha = repo.head.commit.hexsha

        if head_sha == last_sha:
            logger.info("Already up to date — nothing to do")
            return 0

        changeset = compute_changeset(repo_id, repo_path, last_sha, head_sha)

        pipeline = IncrementalIngestionPipeline(
            vector_store=vector_store,  # type: ignore[arg-type]
            graph_store=graph_store,  # type: ignore[arg-type]
            parser=parser,
        )
        result = pipeline.run(changeset)

        # Update last indexed commit on success or partial success
        if result.is_success or result.is_partial:
            graph_store.update_last_indexed_commit(repo_id, head_sha)

        return _log_and_exit_code(result, label="INCREMENTAL INGESTION")

    except Exception as e:
        logger.error(f"Fatal error during incremental ingestion: {e}", exc_info=True)
        return 3


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingest <repo_path_or_url> [repo_id]")
        print()
        print("Examples:")
        print("  python -m src.ingest /path/to/local/repo")
        print("  python -m src.ingest https://github.com/user/repo.git")
        sys.exit(1)

    repo_path = sys.argv[1]
    repo_id = sys.argv[2] if len(sys.argv) >= 3 else None

    sys.exit(ingest_repo(repo_id, repo_path))
