"""
Clew Engine: Adapter Base Protocols

This module defines the abstract interfaces (Protocols) for pluggable backends.
Concrete implementations (Qdrant, Neo4j, OpenAI, etc.) live in separate modules.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from typing_extensions import TypedDict

# =============================================================================
# TypedDicts — named shapes for previously-untyped dicts
# =============================================================================


class CodeMetadata(TypedDict, total=False):
    """Payload attached to a vector search result (Qdrant/pgvector point)."""

    text: str
    path: str
    repo: str
    repo_id: str
    type: str
    name: str
    language: str


class SearchFilters(TypedDict, total=False):
    """Optional filters for vector search."""

    path: str
    path_contains: str
    type: str


class PRData(TypedDict, total=False):
    """Data for creating or merging a PullRequest node in the graph."""

    number: int
    repo_id: str
    title: str
    url: str
    state: str
    author: str
    created_at: str
    base_branch: str
    head_branch: str


class GraphStats(TypedDict):
    """Statistics returned by GraphStore.get_stats()."""

    node_count: int
    edge_count: int
    density: float


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SearchResult:
    """A single result from vector search."""

    id: str
    score: float
    content: str
    metadata: CodeMetadata


@dataclass
class GraphNode:
    """A node in the code graph."""

    id: str
    label: str
    properties: dict[str, Any]


@dataclass
class GraphEdge:
    """An edge in the code graph."""

    id: str
    source: str
    target: str
    type: str
    properties: dict[str, Any]


@dataclass
class GraphResult:
    """Result from graph traversal."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]


# =============================================================================
# Provider Protocols
# =============================================================================


@runtime_checkable
class VectorStore(Protocol):
    """
    Protocol for vector database backends.

    Implementations:
    - QdrantStore (default)
    - PgVectorStore (future)
    """

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        repo: str | None = None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors."""
        ...

    async def upsert(self, id: str, content: str, vector: list[float], metadata: CodeMetadata | None = None) -> None:
        """Insert or update a vector."""
        ...


@runtime_checkable
class GraphStore(Protocol):
    """
    Protocol for graph database backends.

    Implementations:
    - Neo4jStore (default)
    - MemgraphStore (future)
    """

    async def traverse(
        self, start_id: str, depth: int = 2, relationship_types: list[str] | None = None, repo_id: str | None = None
    ) -> GraphResult:
        """
        Traverse the graph from a starting node.

        Args:
            start_id: The path/ID of the starting node
            depth: How many hops to traverse (currently ignored, uses 1)
            relationship_types: Edge types to include (IMPORTS, CALLS, etc.)
            repo_id: Optional repository ID to scope traversal to a single repo

        Returns:
            GraphResult with nodes and edges
        """
        ...

    async def create_pr_node(self, pr_data: PRData) -> str:
        """
        Create a PullRequest node in the graph.

        Args:
            pr_data: PR metadata (number, title, url, etc.)

        Returns:
            The ID of the created PR node
        """
        ...

    async def link_pr_to_files(self, pr_number: int, repo_id: str, file_paths: list[str]) -> None:
        """
        Link a PR node to the files it modified.

        Args:
            pr_number: The PR number
            repo_id: The repository ID
            file_paths: List of file paths modified by the PR
        """
        ...

    async def get_file_pull_requests(self, file_path: str, repo_id: str | None = None) -> list[GraphNode]:
        """
        Get all PRs that modified a specific file.

        Args:
            file_path: The path of the file
            repo_id: Optional repository ID to filter by

        Returns:
            List of PullRequest nodes
        """
        ...

    async def get_pr_impact(self, pr_number: int, repo_id: str) -> GraphResult:
        """
        Get the impact of a PR (files and functions modified).

        Args:
            pr_number: The PR number
            repo_id: The repository ID

        Returns:
            GraphResult with impacted nodes and edges
        """
        ...

    async def get_neighbors_batch(self, paths: list[str], repo_id: str | None = None) -> dict[str, list[str]]:
        """
        Return 1-hop IMPORTS/CALLS neighbors for a batch of file paths.

        Args:
            paths: File paths to look up neighbors for
            repo_id: Optional repository filter

        Returns:
            Mapping of each input path to its neighbor paths
        """
        ...

    async def get_stats(self, repo_id: str | None = None) -> GraphStats:
        """
        Get graph statistics (node count, edge count).

        Args:
            repo_id: Optional repository filter. When provided, counts are
                scoped to that repository only.

        Returns:
            GraphStats with node_count, edge_count, and density
        """
        ...

    async def create_policy(self, policy: dict[str, Any]) -> str:
        """Create or update a PolicyRule node. Returns the policy ID."""
        ...

    async def get_policies(self) -> list[dict[str, Any]]:
        """Return all active PolicyRule nodes."""
        ...

    async def delete_policy(self, policy_id: str) -> bool:
        """Delete a PolicyRule node by ID. Returns True if deleted."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Protocol for embedding generation.

    Implementations:
    - OpenAIEmbeddings
    - OllamaEmbeddings
    - HashEmbeddings (fallback)
    """

    async def embed(self, text: str) -> list[float]:
        """
        Generate an embedding vector for the given text.

        Args:
            text: The text to embed

        Returns:
            A list of floats representing the embedding
        """
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a batch of texts.

        Args:
            texts: The texts to embed

        Returns:
            A list of embedding vectors, one per input text
        """
        ...

    @property
    def dimension(self) -> int:
        """The dimensionality of embeddings produced by this provider."""
        ...
