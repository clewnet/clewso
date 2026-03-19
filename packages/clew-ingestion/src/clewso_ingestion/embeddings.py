"""
Re-export shim.

The canonical embeddings implementation now lives in `clew-core`.
This module re-exports it for backward compatibility.
"""

from clewso_core.embeddings import (  # noqa: F401
    HashEmbeddings,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    get_embedding_provider,
)

__all__ = [
    "OpenAIEmbeddings",
    "OllamaEmbeddings",
    "HashEmbeddings",
    "get_embedding_provider",
]
