"""
Base protocols and interfaces for the ingestion pipeline.

Defines the contracts that pipeline stages and node processors must follow.
"""

from typing import Protocol, runtime_checkable

from .context import IngestionContext, ProcessingResult


@runtime_checkable
class PipelineStage(Protocol):
    """
    Protocol defining the interface for a synchronous pipeline stage.

    Each stage is responsible for one specific concern in the ingestion process.
    Stages follow the Chain of Responsibility pattern, where each stage
    processes the context and passes it to the next stage.
    """

    name: str

    def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Execute this pipeline stage synchronously.

        Args:
            context: The shared ingestion context containing state and resources

        Returns:
            ProcessingResult indicating success/failure and any errors

        Raises:
            StageError: If the stage encounters a fatal error
        """
        ...


@runtime_checkable
class AsyncPipelineStage(Protocol):
    """
    Protocol defining the interface for an async pipeline stage.

    Async stages are used for I/O-bound work (embedding API calls, graph writes)
    where concurrency within the stage provides significant speedup. The
    orchestrator detects async stages via presence of async execute() and awaits them.
    """

    name: str

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Execute this pipeline stage asynchronously.

        Args:
            context: The shared ingestion context containing state and resources

        Returns:
            ProcessingResult indicating success/failure and any errors

        Raises:
            StageError: If the stage encounters a fatal error
        """
        ...


@runtime_checkable
class NodeProcessor(Protocol):
    """
    Protocol for processing different types of AST nodes.

    This enables the Strategy pattern, where different node types
    (definitions, imports, calls) are handled by specialized processors.
    """

    node_type: str

    def process(self, node_data: dict, context: IngestionContext) -> ProcessingResult:
        """
        Process a single AST node.

        Args:
            node_data: Dictionary containing node information (type, name, content, etc.)
            context: The shared ingestion context

        Returns:
            ProcessingResult indicating success/failure
        """
        ...
