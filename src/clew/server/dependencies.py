"""
Dependency injection for Clew adapters.

Provides FastAPI dependencies for injecting adapters into routes.
Supports runtime adapter selection via environment variables.

This module now uses the dynamic adapter registry system, which eliminates
hardcoded if/else chains and follows the Open/Closed Principle. New adapters
can be added by simply registering them without modifying this file.
"""

import logging
import os
from functools import lru_cache

from clew.server.adapters import (
    EmbeddingProvider,
    GraphStore,
    VectorStore,
    get_embedding_provider,
    graph_store_registry,
    vector_store_registry,
)
from clew.server.adapters.reranker import CrossEncoderReranker, NoOpReranker, Reranker

logger = logging.getLogger(__name__)


@lru_cache
def get_vector_store() -> VectorStore:
    """
    Get the configured vector store using the adapter registry.

    The adapter is selected based on the CLEW_VECTOR_ADAPTER environment variable.
    Available adapters are dynamically registered and can be extended without
    modifying this code.

    Supported adapters (as of now):
    - qdrant (default): Qdrant vector database
    - pgvector: PostgreSQL with pgvector extension

    To add a new adapter:
    1. Implement the VectorStore protocol
    2. Register it with vector_store_registry.register("name", factory)
    3. Set CLEW_VECTOR_ADAPTER=name

    Environment:
        CLEW_VECTOR_ADAPTER: Name of the vector store adapter to use (default: qdrant)

    Returns:
        VectorStore instance

    Raises:
        ValueError: If the specified adapter is not registered
    """
    adapter_name = os.getenv("CLEW_VECTOR_ADAPTER", "qdrant").lower()
    logger.info(f"Loading vector store adapter: {adapter_name}")

    try:
        return vector_store_registry.get(adapter_name)
    except ValueError as e:
        # Re-raise with more helpful context
        available = ", ".join(vector_store_registry.list_adapters())
        raise ValueError(
            f"Vector store adapter '{adapter_name}' not found. "
            f"Available adapters: {available}. "
            f"Set CLEW_VECTOR_ADAPTER to one of these values."
        ) from e


@lru_cache
def get_graph_store() -> GraphStore:
    """
    Get the configured graph store using the adapter registry.

    The adapter is selected based on the CLEW_GRAPH_ADAPTER environment variable.
    Available adapters are dynamically registered and can be extended without
    modifying this code.

    Supported adapters (as of now):
    - neo4j (default): Neo4j graph database
    - noop: No-op implementation (disables graph traversal)

    To add a new adapter:
    1. Implement the GraphStore protocol
    2. Register it with graph_store_registry.register("name", factory)
    3. Set CLEW_GRAPH_ADAPTER=name

    Environment:
        CLEW_GRAPH_ADAPTER: Name of the graph store adapter to use (default: neo4j)

    Returns:
        GraphStore instance

    Raises:
        ValueError: If the specified adapter is not registered
    """
    adapter_name = os.getenv("CLEW_GRAPH_ADAPTER", "neo4j").lower()
    logger.info(f"Loading graph store adapter: {adapter_name}")

    try:
        return graph_store_registry.get(adapter_name)
    except ValueError as e:
        # Re-raise with more helpful context
        available = ", ".join(graph_store_registry.list_adapters())
        raise ValueError(
            f"Graph store adapter '{adapter_name}' not found. "
            f"Available adapters: {available}. "
            f"Set CLEW_GRAPH_ADAPTER to one of these values."
        ) from e


def get_embeddings() -> EmbeddingProvider:
    """
    Get the configured embedding provider.

    This still uses the legacy get_embedding_provider() function.
    Future enhancement: Migrate embeddings to use the registry system as well.
    """
    return get_embedding_provider()


@lru_cache
def get_reranker() -> Reranker:
    """
    Get the configured reranker.

    Environment:
        CLEW_RERANK_ENABLED: Boolean to enable reranking (default: false)
        CLEW_RERANK_MODEL: Cross-encoder model name
    """
    enabled = os.getenv("CLEW_RERANK_ENABLED", "false").lower() == "true"
    if not enabled:
        return NoOpReranker()

    model_name = os.getenv("CLEW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    return CrossEncoderReranker(model_name=model_name)
