"""
Search endpoint - refactored to use adapters.
"""

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from clew.server.adapters import EmbeddingProvider, GraphStore, HashEmbeddings, VectorStore
from clew.server.adapters.base import SearchFilters, SearchResult
from clew.server.adapters.reranker import Reranker
from clew.server.dependencies import get_embeddings, get_graph_store, get_reranker, get_vector_store

# Graph boost weight — how much each co-occurring neighbor adds to score
GRAPH_BOOST_WEIGHT = float(os.getenv("CLEW_GRAPH_BOOST_WEIGHT", "0.05"))

router = APIRouter()
logger = logging.getLogger("clew.routes.search")


def is_test_file(path: str) -> bool:
    """
    Check if a file path is a test file.

    Filters out common test file patterns:
    - test_*.py, *_test.py, *_test.js, etc.
    - Files in test directories (tests/, __tests__/, test/)
    - Spec files (*.spec.js, *.spec.ts, etc.)
    """
    path_obj = Path(path)
    filename = path_obj.name.lower()
    parts = [p.lower() for p in path_obj.parts]

    # Check filename patterns
    if filename.startswith("test_") or filename.endswith("_test.py"):
        return True
    if filename.endswith((".spec.js", ".spec.ts", ".spec.jsx", ".spec.tsx")):
        return True
    if filename.endswith((".test.js", ".test.ts", ".test.jsx", ".test.tsx")):
        return True

    # Check directory patterns
    test_dirs = {"tests", "__tests__", "test", "spec", "__test__"}
    if any(part in test_dirs for part in parts):
        return True

    return False


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(10, gt=0, le=100)
    repo: str | None = Field(None, max_length=512)
    filters: SearchFilters | None = None
    exclude_tests: bool = Field(True, description="Filter out test files from results")
    rerank: bool = Field(False, description="Enable cross-encoder reranking")
    graph_boost: bool = Field(True, description="Enable graph co-occurrence boosting")


def apply_graph_boost(results: list[SearchResult], neighbors: dict[str, list[str]]) -> list[SearchResult]:
    """Boost scores of results whose graph neighbors also appear in the result set."""
    result_paths = {r.metadata.get("path", "") for r in results}

    for r in results:
        path = r.metadata.get("path", "")
        neighbor_paths = neighbors.get(path, [])
        overlap = sum(1 for n in neighbor_paths if n in result_paths and n != path)
        if overlap > 0:
            r.score += overlap * GRAPH_BOOST_WEIGHT

    results.sort(key=lambda x: x.score, reverse=True)
    return results


class SearchResultResponse(BaseModel):
    id: str
    score: float
    content: str
    metadata: dict[str, Any]


async def _apply_reranking(query: str, results: list[SearchResult], reranker: Reranker) -> list[SearchResult]:
    """Rerank results using a cross-encoder model. Falls back to original order on error."""
    logger.info(f"Reranking {len(results)} results for query: {query}")
    try:
        documents = [r.content for r in results]
        scores = await reranker.rerank(query, documents)
        for r, score in zip(results, scores, strict=True):
            r.score = score
        results.sort(key=lambda x: x.score, reverse=True)
        logger.debug("Reranking complete")
    except Exception as e:
        logger.error(f"Reranking failed: {e}")
    return results


def _compute_search_multiplier(request: "SearchRequest") -> float:
    """Compute how many extra candidates to fetch for filtering/boosting/reranking."""
    multiplier: float = 10 if request.rerank else 1
    if request.exclude_tests:
        multiplier += 0.5
    if request.graph_boost:
        multiplier += 2
    return multiplier


@router.post("/", response_model=list[SearchResultResponse])
async def search(
    request: SearchRequest,
    vector_store: VectorStore = Depends(get_vector_store),
    embeddings: EmbeddingProvider = Depends(get_embeddings),
    reranker: Reranker = Depends(get_reranker),
    graph_store: GraphStore = Depends(get_graph_store),
):
    """
    Search the codebase using semantic similarity.

    Uses injected adapters for vector store and embeddings,
    making the endpoint pluggable for different backends.
    """
    # Generate embedding
    try:
        query_vector = await embeddings.embed(request.query)
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        query_vector = await HashEmbeddings().embed(request.query)
        logger.warning("Using hash fallback due to embedding error")

    # Search (fetch extra results to account for filtering, boosting, and reranking)
    search_limit = int(request.limit * _compute_search_multiplier(request))
    try:
        results = await vector_store.search(
            query_vector=query_vector,
            limit=search_limit,
            repo=request.repo,
            filters=request.filters,
        )
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        raise HTTPException(status_code=503, detail="Vector search service unavailable") from e

    # Filter test files if requested
    if request.exclude_tests:
        results = [r for r in results if not is_test_file(r.metadata.get("path", ""))]
        logger.debug(f"Filtered test files, {len(results)} candidates remaining")

    # Graph co-occurrence boost
    if request.graph_boost and graph_store and len(results) > 1:
        try:
            paths = [r.metadata.get("path", "") for r in results]
            neighbors = await graph_store.get_neighbors_batch(paths, repo_id=request.repo)
            results = apply_graph_boost(results, neighbors)
            logger.debug("Graph boost applied")
        except Exception as e:
            logger.warning(f"Graph boost failed, skipping: {e}")

    # Apply reranking
    if request.rerank and results:
        results = await _apply_reranking(request.query, results, reranker)

    # Trim to requested limit
    results = results[: request.limit]
    return [SearchResultResponse(id=r.id, score=r.score, content=r.content, metadata=dict(r.metadata)) for r in results]
