"""
Embedding Provider Implementations

Consolidated from clew-api and clew-ingestion packages.
Provides:
  - OpenAIEmbeddings  — OpenAI async embeddings with batching
  - OllamaEmbeddings  — Ollama local embeddings with batching
  - HashEmbeddings    — Deterministic hash-based fallback (testing only)
  - get_embedding_provider() — factory based on environment variables
"""

import asyncio
import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIEmbeddings:
    """OpenAI async embedding provider with optional batch support."""

    _MAX_BATCH = 2048

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model: str = str(model or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"))
        self.dimensions: int = dimensions or int(os.getenv("EMBEDDING_DIMENSION", "1536"))

        self._client = None  # lazily created by _get_client()

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set. Set it in environment or pass to constructor.")

    @property
    def dimension(self) -> int:
        return self.dimensions

    def _get_client(self):
        """Return a cached AsyncOpenAI client (lazy-initialised)."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate embedding using the OpenAI API."""
        try:
            response = await self._get_client().embeddings.create(
                input=text, model=self.model, dimensions=self.dimensions
            )
            logger.debug(f"OpenAI embedding generated ({self.model}, dims={self.dimensions})")
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"OpenAI embedding failed: {e}", exc_info=True)
            raise

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed texts. Automatically chunks into ≤2 048-input requests."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        try:
            client = self._get_client()
            for i in range(0, len(texts), self._MAX_BATCH):
                chunk = texts[i : i + self._MAX_BATCH]
                response = await client.embeddings.create(input=chunk, model=self.model, dimensions=self.dimensions)
                all_embeddings.extend(item.embedding for item in response.data)
            logger.debug(f"OpenAI batch embedding: {len(texts)} texts ({self.model})")
            return all_embeddings
        except Exception as e:
            logger.error(f"OpenAI batch embedding failed: {e}", exc_info=True)
            raise


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class OllamaEmbeddings:
    """Ollama local embedding provider with concurrent batching."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = model or os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self.timeout = timeout if timeout is not None else float(os.getenv("OLLAMA_TIMEOUT", "10.0"))
        self._client = httpx.AsyncClient(timeout=self.timeout)

    @property
    def dimension(self) -> int:
        """Dimension reported by this provider.

        Ollama's embedding dimension is model-dependent and cannot be determined
        statically. Falls back to EMBEDDING_DIMENSION env var (default 1536).
        See OllamaEmbeddings docs for how to configure per-model dimensions.
        """
        return int(os.getenv("EMBEDDING_DIMENSION", "1536"))

    async def close(self) -> None:
        """Close the shared HTTP client."""
        await self._client.aclose()

    async def embed(self, text: str) -> list[float]:
        """Generate embedding using the Ollama API."""
        try:
            response = await self._client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                logger.debug(f"Ollama embedding generated ({self.model})")
                return response.json()["embedding"]
            raise ValueError(f"Ollama API error: {response.status_code} - {response.text}")
        except httpx.RequestError as e:
            logger.error(f"Ollama embedding network error: {e}", exc_info=True)
            raise
        except (ValueError, KeyError) as e:
            logger.error(f"Ollama embedding processing error: {e}", exc_info=True)
            raise

    async def embed_batch(self, texts: list[str], concurrency: int = 8) -> list[list[float]]:
        """Batch embed via concurrent single-item calls (Ollama has no batch API)."""
        if not texts:
            return []

        sem = asyncio.Semaphore(concurrency)

        async def _embed_one(text: str) -> list[float]:
            async with sem:
                return await self.embed(text)

        results = await asyncio.gather(*[_embed_one(t) for t in texts])
        logger.debug(f"Ollama batch embedding: {len(texts)} texts ({self.model})")
        return list(results)


# ---------------------------------------------------------------------------
# Hash fallback
# ---------------------------------------------------------------------------


class HashEmbeddings:
    """
    Deterministic hash-based embeddings.

    NOT suitable for production semantic search.
    Useful for testing or offline CI runs.
    """

    def __init__(self, dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "1536"))):
        # NOTE: The default is evaluated once at import time (standard Python
        # default-argument behaviour). If EMBEDDING_DIMENSION is set in the
        # environment *after* this module is imported, pass dimension= explicitly.
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        """Generate a deterministic pseudo-embedding from the text hash."""
        random.seed(hash(text))
        embedding = [random.random() for _ in range(self._dimension)]
        logger.warning("Using hash fallback for embeddings (not semantic)")
        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed using the hash fallback."""
        return [await self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_embedding_provider() -> OpenAIEmbeddings | OllamaEmbeddings | HashEmbeddings:
    """
    Return an embedding provider based on environment variables.

    Priority:
    1. OpenAI (OPENAI_API_KEY set)
    2. Ollama (OLLAMA_BASE_URL set)
    3. Hash fallback (neither configured)
    """
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIEmbeddings()
    if os.getenv("OLLAMA_BASE_URL"):
        return OllamaEmbeddings()
    logger.warning("No embedding provider configured — using hash fallback")
    return HashEmbeddings()
