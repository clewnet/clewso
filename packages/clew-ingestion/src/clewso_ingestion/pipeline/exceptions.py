"""
Custom exceptions for the ingestion pipeline.

These exceptions provide better context and enable structured error handling.
"""


class IngestionError(Exception):
    """Base exception for all ingestion errors."""

    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


class StageError(IngestionError):
    """Raised when a pipeline stage encounters a fatal error."""

    def __init__(self, stage_name: str, message: str, context: dict | None = None):
        self.stage_name = stage_name
        super().__init__(f"[{stage_name}] {message}", context)


class ParsingError(IngestionError):
    """Raised when AST parsing fails."""

    def __init__(self, file_path: str, message: str, context: dict | None = None):
        self.file_path = file_path
        super().__init__(f"Parsing failed for {file_path}: {message}", context)


class RepositoryError(IngestionError):
    """Raised when repository operations fail (clone, validation, etc.)."""

    pass


class DatabaseError(IngestionError):
    """Raised when database operations fail (vector store or graph store)."""

    pass
