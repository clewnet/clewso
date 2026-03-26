"""
Context objects and DTOs for the ingestion pipeline.

These classes encapsulate data that flows between pipeline stages,
ensuring clean separation of concerns and testability.
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ProcessingStatus(Enum):
    """Status of a processing operation."""

    SUCCESS = "success"
    PARTIAL = "partial"  # Some items failed but processing continued
    FAILED = "failed"


@dataclass
class ProcessingResult:
    """
    Result of a pipeline stage or node processor execution.

    Attributes:
        status: Overall status of the operation
        message: Human-readable description
        errors: List of errors encountered (file paths and error messages)
        items_processed: Number of items successfully processed
        items_failed: Number of items that failed
        metadata: Additional stage-specific information
    """

    status: ProcessingStatus
    message: str
    errors: list[dict[str, str]] = field(default_factory=list)
    items_processed: int = 0
    items_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Check if operation was fully successful."""
        return self.status == ProcessingStatus.SUCCESS

    @property
    def is_partial(self) -> bool:
        """Check if operation had partial success."""
        return self.status == ProcessingStatus.PARTIAL

    def add_error(self, context: str, error: str):
        """Add an error to the result."""
        self.errors.append({"context": context, "error": error})
        self.items_failed += 1


@dataclass
class ChangeSet:
    """Delta produced by a commit or webhook event.

    Attributes:
        repo_id: Unique repository identifier (e.g. ``"owner/repo"``).
        repo_path: Local filesystem path to the repository checkout at the
            relevant commit.  The pipeline reads files from this path and
            does not perform any cloning.
        commit_sha: The commit that produced this changeset.
        added: Relative paths of newly added files.
        modified: Relative paths of files whose content changed.
        removed: Relative paths of files that were deleted.
    """

    repo_id: str
    repo_path: str
    commit_sha: str
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class FileItem:
    """
    Represents a file to be processed in the pipeline.

    Attributes:
        path: Relative path from repository root
        absolute_path: Full filesystem path
        content: File content as string (lazy-loaded)
        metadata: Additional file metadata (language, size, etc.)
    """

    path: str
    absolute_path: Path
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def load_content(self) -> str:
        """
        Lazy-load file content.

        Returns:
            File content as UTF-8 string

        Raises:
            IOError: If file cannot be read
        """
        if self.content is None:
            with open(self.absolute_path, "rb") as f:
                content_bytes = f.read()
            self.content = content_bytes.decode("utf-8", errors="ignore")
        return self.content


@dataclass
class ParsedNode:
    """
    Represents an AST node extracted from a file.

    Attributes:
        type: Type of node (definition, import, call)
        kind: Specific kind from tree-sitter (function_definition, class_definition, etc.)
        name: Name of the node (function name, class name, etc.)
        content: Source code content
        start_line: Starting line number
        end_line: Ending line number
        file_path: Path to the file containing this node
        metadata: Additional node-specific data
    """

    type: str
    kind: str
    name: str
    content: str
    start_line: int
    end_line: int
    file_path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestionContext:
    """
    Shared context for the entire ingestion pipeline.

    This context is passed through all pipeline stages and contains:
    - Repository information
    - Database connections
    - Processed items
    - Configuration

    Attributes:
        repo_name: Name of the repository being ingested
        repo_url: URL or local path to the repository
        temp_dir: Temporary directory for cloned repositories
        files: List of files discovered and to be processed
        nodes: List of AST nodes extracted from files
        vector_store: Vector database connection (injected)
        graph_store: Graph database connection (injected)
        parser: Code parser instance (injected)
        config: Configuration dictionary
    """

    repo_id: str
    repo_name: str
    repo_url: str
    temp_dir: Path
    files: list[FileItem] = field(default_factory=list)
    nodes: list[ParsedNode] = field(default_factory=list)
    vector_buffer: list[tuple[str, dict[str, Any], str | None]] = field(default_factory=list)
    vector_store: Any = None  # Will be VectorStore instance
    graph_store: Any = None  # Will be GraphStore instance
    parser: Any = None  # Will be CodeParser instance
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    graph_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def is_local_repo(self) -> bool:
        """Check if repository is a local directory."""
        return Path(self.repo_url).is_dir()
