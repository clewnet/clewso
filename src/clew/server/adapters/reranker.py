import abc
import asyncio
import logging
from typing import Any

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None  # type: ignore[assignment,misc]

logger = logging.getLogger("clew.adapters.reranker")


class Reranker(abc.ABC):
    """Abstract base class for reranking search results."""

    @abc.abstractmethod
    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """
        Rerank a list of documents based on a query.

        Returns:
            List of scores corresponding to each document.
        """
        pass


class CrossEncoderReranker(Reranker):
    """
    Reranker implementation using a Cross-Encoder model.

    Default model: BAAI/bge-reranker-v2-m3 (8192 token context window).
    Previous model (ms-marco-MiniLM-L-6-v2) had a 512 token limit which
    caused silent truncation of code snippets, degrading reranking quality.
    """

    # Safety margin below model's max to account for tokenization variance
    MAX_TOKENS = 7500

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self) -> Any:
        if self._model is None:
            if CrossEncoder is None:
                logger.error("sentence-transformers not installed. Reranking will be disabled.")
                return None
            logger.info(f"Loading Cross-Encoder model: {self.model_name}")
            self._model = CrossEncoder(self.model_name)
        return self._model

    def _truncate(self, text: str) -> str:
        """
        Truncate text to fit within model's token limit (approximate).

        Strategy: Keep the beginning (imports/signature) and the end (return statements),
        discarding the middle if necessary. This handles code better than prefix truncation.
        """
        # Rough estimate: 1 token ≈ 4 characters for code
        # ms-marco-MiniLM-L-6-v2 limit is 512 tokens -> ~2048 chars
        # Using 2000 chars as safety limit
        max_chars = 2000

        if len(text) <= max_chars:
            return text

        logger.debug(f"Truncating document from {len(text)} chars (Smart Truncation: Head+Tail)")

        # Keep 50% head, 50% tail
        half_window = (max_chars - 20) // 2  # subtract buffer for separator
        return text[:half_window] + "\n...[TRUNCATED]...\n" + text[-half_window:]

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """
        Rerank documents using the Cross-Encoder.
        """
        if not documents:
            return []

        model = self.model
        if model is None:
            # Fallback: maintain original ordering by returning flat scores
            return [1.0 - (i / len(documents)) for i in range(len(documents))]

        # Cross-Encoder expects pairs of (query, doc)
        pairs = [(query, self._truncate(doc)) for doc in documents]

        # Run synchronous model prediction in a threadpool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(None, model.predict, pairs)

        # Convert to list if it's a numpy array, otherwise return as is
        return scores.tolist() if hasattr(scores, "tolist") else scores


class NoOpReranker(Reranker):
    """Default reranker that does nothing (maintains original ordering)."""

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [1.0] * len(documents)
