"""
Direct store access for CLI commands.

Instantiates vector/graph/embedding stores from ClewsoConfig,
bypassing the HTTP API server entirely.
"""

from __future__ import annotations

from pathlib import Path

from .config import ClewsoConfig, get_config


def resolve_ladybug_path(cfg: ClewsoConfig) -> str:
    """Resolve the LadybugDB database path, expanding ~ and normalizing for cache consistency."""
    return str(Path(cfg.store.ladybug_path).expanduser().resolve())


def _get_ladybug_store(cfg: ClewsoConfig):
    """Get or create a shared LadybugUnifiedStore instance."""
    from clew.server.adapters import LadybugUnifiedStore

    path = resolve_ladybug_path(cfg)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        return LadybugUnifiedStore.get_or_create(path, cfg.embeddings.dimension)
    except Exception as e:
        err = str(e)
        if "corrupt" in err.lower() or "invalid" in err.lower() or "cannot open" in err.lower():
            raise RuntimeError(
                f"LadybugDB database at {path} appears corrupted. "
                f"Delete the directory and re-index: rm -rf {path} && clewso index <repo>"
            ) from e
        if "lock" in err.lower() or "busy" in err.lower():
            raise RuntimeError(
                f"LadybugDB database at {path} is locked by another process. Close other clewso sessions and try again."
            ) from e
        raise


def get_graph_store(cfg: ClewsoConfig | None = None):
    """Create a graph store from config."""
    cfg = cfg or get_config()
    if cfg.server.graph_adapter == "ladybug":
        return _get_ladybug_store(cfg)
    if cfg.server.graph_adapter == "noop":
        from clew.server.adapters import NoOpGraphStore

        return NoOpGraphStore()
    from clew.server.adapters import Neo4jStore

    return Neo4jStore(
        uri=cfg.store.neo4j_uri,
        user=cfg.store.neo4j_user,
        password=cfg.store.neo4j_password,
    )


def get_vector_store(cfg: ClewsoConfig | None = None):
    """Create a vector store from config."""
    cfg = cfg or get_config()
    if cfg.server.vector_adapter == "ladybug":
        return _get_ladybug_store(cfg)
    from clew.server.adapters import QdrantStore

    return QdrantStore(
        host=cfg.store.qdrant_host,
        port=cfg.store.qdrant_port,
        url=cfg.store.qdrant_url,
        api_key=cfg.store.qdrant_api_key,
        collection_name=cfg.store.qdrant_collection,
    )


def get_embeddings(cfg: ClewsoConfig | None = None):
    """Create an embedding provider from config."""
    from clew.server.adapters import HashEmbeddings, OllamaEmbeddings, OpenAIEmbeddings

    cfg = cfg or get_config()
    if cfg.embeddings.provider == "ollama":
        return OllamaEmbeddings(
            base_url=cfg.embeddings.ollama_url,
            model=cfg.embeddings.ollama_model,
        )
    if cfg.embeddings.openai_api_key:
        return OpenAIEmbeddings(
            api_key=cfg.embeddings.openai_api_key,
            model=cfg.embeddings.openai_model,
        )
    return HashEmbeddings()
