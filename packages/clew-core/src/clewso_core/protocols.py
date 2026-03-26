"""
Write-side storage protocols for Clewso ingestion pipeline.

These protocols define the interface that ingestion backends must implement.
Extracted from the concrete Neo4j (GraphStore) and Qdrant (VectorStore) classes
in clewso-ingestion to enable pluggable backends (e.g., LadybugDB).

Query-side protocols (VectorStore, GraphStore) live in clew.server.adapters.base.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorWriter(Protocol):
    """
    Protocol for vector store write operations during ingestion.

    Implementations:
    - VectorStore in clewso_ingestion/vector.py (Qdrant, existing)
    - LadybugDB (planned)
    """

    async def add(self, text: str, metadata: dict[str, Any]) -> str:
        """Add a text entry, generating and buffering its embedding. Returns point ID."""
        ...

    async def add_batch(
        self,
        items: list[tuple[str, dict[str, Any], str | None]],
    ) -> list[str]:
        """Add multiple text entries in one batch. Returns list of point IDs."""
        ...

    async def flush(self) -> None:
        """Flush buffered writes to the store."""
        ...

    async def delete(self, id: str) -> None:
        """Delete a single vector by its ID."""
        ...

    def delete_by_filter(self, repo_id: str, file_path: str) -> int:
        """Delete vectors matching repo_id and file path. Returns count deleted."""
        ...

    def delete_files_batch(self, repo_id: str, file_paths: list[str]) -> int:
        """Delete vectors for multiple files in a single bulk call. Returns count deleted."""
        ...


@runtime_checkable
class GraphWriter(Protocol):
    """
    Protocol for graph store write operations during ingestion.

    Implementations:
    - GraphStore in clewso_ingestion/graph.py (Neo4j, existing)
    - LadybugDB (planned)
    """

    def close(self) -> None:
        """Close the graph store connection."""
        ...

    def execute_batch(self, operations: list[tuple[str, dict[str, Any]]]) -> None:
        """Execute multiple queries in a single transaction."""
        ...

    def get_last_indexed_commit(self, repo_id: str) -> str | None:
        """Return the last_indexed_commit SHA for a repo, or None if never indexed."""
        ...

    def update_last_indexed_commit(self, repo_id: str, commit_sha: str) -> None:
        """Store the commit SHA that was just indexed."""
        ...

    def create_repo_node(self, repo_id: str, name: str, url: str) -> None:
        """Create or merge a Repository node."""
        ...

    def create_file_node(self, repo_id: str, file_path: str, qdrant_id: str) -> None:
        """Create or merge a File node linked to its Repository."""
        ...

    def create_file_nodes_batch(self, repo_id: str, items: list[dict[str, Any]]) -> None:
        """Create multiple File nodes in a single batch."""
        ...

    def create_code_node(
        self,
        repo_id: str,
        file_path: str,
        name: str,
        node_type: str,
        start_line: int,
        end_line: int,
        qdrant_id: str,
    ) -> None:
        """Create or merge a CodeBlock node linked to its File."""
        ...

    def create_import_relationship(self, repo_id: str, file_path: str, module_name: str) -> None:
        """Create an IMPORTS edge from a File to a Module."""
        ...

    def create_call_relationship(self, repo_id: str, file_path: str, target_name: str) -> None:
        """Create a CALLS edge from a File to a Function."""
        ...

    def delete_file_node(self, repo_id: str, file_path: str) -> int:
        """Delete a File node and its related CodeBlocks. Returns count deleted."""
        ...

    def delete_file_edges(self, repo_id: str, file_path: str) -> None:
        """Delete all outgoing IMPORTS and CALLS edges from a File node."""
        ...

    def delete_files_batch(self, repo_id: str, file_paths: list[str]) -> int:
        """Delete multiple File nodes in a batch. Returns count deleted."""
        ...
