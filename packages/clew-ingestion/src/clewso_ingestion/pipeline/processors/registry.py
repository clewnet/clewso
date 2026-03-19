"""
Node Processor Registry.

Implements the Registry pattern to map node types to their processors.
This eliminates if/elif chains and follows the Open/Closed Principle.
"""

import logging

from ..base import NodeProcessor
from ..context import IngestionContext, ProcessingResult, ProcessingStatus

logger = logging.getLogger(__name__)


class NodeProcessorRegistry:
    """
    Registry for mapping node types to their processors.

    This allows dynamic registration of processors and eliminates
    hardcoded if/elif switch statements.

    Example:
        registry = NodeProcessorRegistry()
        registry.register("definition", DefinitionProcessor())
        registry.register("import", ImportProcessor())

        result = registry.process(node_data, context)
    """

    def __init__(self):
        self._processors: dict[str, NodeProcessor] = {}

    def register(self, node_type: str, processor: NodeProcessor):
        """
        Register a processor for a specific node type.

        Args:
            node_type: The type of node this processor handles
            processor: The processor instance
        """
        logger.debug(f"Registering processor for node type: {node_type}")
        self._processors[node_type] = processor

    def process(self, node_data: dict, context: IngestionContext) -> ProcessingResult:
        """
        Process a node using the appropriate registered processor.

        Args:
            node_data: Dictionary containing node information
            context: The shared ingestion context

        Returns:
            ProcessingResult from the processor, or error if no processor found
        """
        node_type = node_data.get("type", "unknown")

        processor = self._processors.get(node_type)
        if not processor:
            logger.warning(f"No processor registered for node type: {node_type}")
            return ProcessingResult(
                status=ProcessingStatus.FAILED,
                message=f"No processor for node type: {node_type}",
            )

        try:
            return processor.process(node_data, context)
        except Exception as e:
            logger.error(f"Processor failed for {node_type}: {e}", exc_info=True)
            result = ProcessingResult(
                status=ProcessingStatus.FAILED,
                message=f"Processor error: {str(e)}",
            )
            result.add_error(
                context=(f"{node_data.get('name', 'unknown')} at {node_data.get('file_path', 'unknown')}"),
                error=str(e),
            )
            return result

    def has_processor(self, node_type: str) -> bool:
        """Check if a processor is registered for the given type."""
        return node_type in self._processors

    def get_registered_types(self) -> list:
        """Get list of all registered node types."""
        return list(self._processors.keys())
