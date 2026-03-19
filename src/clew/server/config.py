"""Server settings — bridged from unified clew.config."""

from __future__ import annotations

from dataclasses import dataclass

from clew.config import get_config


@dataclass
class Settings:
    """Compatibility shim exposing the same attribute names the server code expects."""

    APP_NAME: str = "Clew API"
    APP_VERSION: str = "0.1.0"

    # Populated from unified config at construction time
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6335
    QDRANT_COLLECTION: str = "codebase"
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str | None = None
    NEO4J_PASSWORD: str | None = None
    EMBEDDING_DIMENSION: int = 1536
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_TIMEOUT: float = 10.0


def _build_settings() -> Settings:
    cfg = get_config()
    return Settings(
        QDRANT_HOST=cfg.store.qdrant_host,
        QDRANT_PORT=cfg.store.qdrant_port,
        QDRANT_COLLECTION=cfg.store.qdrant_collection,
        NEO4J_URI=cfg.store.neo4j_uri,
        NEO4J_USER=cfg.store.neo4j_user or None,
        NEO4J_PASSWORD=cfg.store.neo4j_password or None,
        EMBEDDING_DIMENSION=cfg.embeddings.dimension,
        OPENAI_EMBEDDING_MODEL=cfg.embeddings.openai_model,
        OLLAMA_EMBEDDING_MODEL=cfg.embeddings.ollama_model,
        OLLAMA_TIMEOUT=cfg.embeddings.ollama_timeout,
    )


settings = _build_settings()
