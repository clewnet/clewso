"""
Base protocols for the ingestion pipeline.

Defines the contracts that pipeline stages and node processors must follow.
"""

from typing import Protocol, runtime_checkable

from .context import IngestionContext, ProcessingResult


@runtime_checkable
class PipelineStage(Protocol):
    """Synchronous pipeline stage following Chain of Responsibility."""

    name: str

    def execute(self, context: IngestionContext) -> ProcessingResult:
        """Execute this stage and return a result."""
        ...


@runtime_checkable
class AsyncPipelineStage(Protocol):
    """Async pipeline stage for I/O-bound work (embeddings, graph writes)."""

    name: str

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        """Execute this stage asynchronously and return a result."""
        ...


@runtime_checkable
class NodeProcessor(Protocol):
    """Strategy for processing a specific AST node type."""

    node_type: str

    def process(self, node_data: dict, context: IngestionContext) -> ProcessingResult:
        """Process a single AST node and return a result."""
        ...
