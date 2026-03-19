"""Clew Engine Adapters - Pluggable backend implementations."""

# Import all adapters to trigger auto-registration
# The imports above already do this, but we're explicit here
from . import neo4j, noop_graph, pgvector, qdrant  # noqa: F401
from .base import (
    EmbeddingProvider,
    GraphEdge,
    GraphNode,
    GraphResult,
    GraphStore,
    SearchResult,
    VectorStore,
)
from .embeddings import (
    HashEmbeddings,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    get_embedding_provider,
)
from .neo4j import Neo4jStore
from .noop_graph import NoOpGraphStore
from .pgvector import PgVectorStore
from .qdrant import QdrantStore

# Import registry to make it available
from .registry import (
    embedding_provider_registry,
    graph_store_registry,
    vector_store_registry,
)
from .reranker import CrossEncoderReranker, NoOpReranker, Reranker

__all__ = [
    # Protocols
    "VectorStore",
    "GraphStore",
    "EmbeddingProvider",
    # Data classes
    "SearchResult",
    "GraphNode",
    "GraphEdge",
    "GraphResult",
    # Vector Store Implementations
    "QdrantStore",
    "PgVectorStore",
    # Graph Store Implementations
    "Neo4jStore",
    "NoOpGraphStore",
    # Embedding Implementations
    "OpenAIEmbeddings",
    "OllamaEmbeddings",
    "HashEmbeddings",
    "get_embedding_provider",
    # Registries
    "vector_store_registry",
    "graph_store_registry",
    "embedding_provider_registry",
    # Reranker
    "Reranker",
    "CrossEncoderReranker",
    "NoOpReranker",
]
