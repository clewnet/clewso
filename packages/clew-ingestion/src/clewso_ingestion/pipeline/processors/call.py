"""
Call processor for handling function call expressions.
"""

import logging

from ..context import IngestionContext, ProcessingResult, ProcessingStatus

logger = logging.getLogger(__name__)


class CallProcessor:
    """
    Processes AST nodes representing function calls.

    Responsibilities:
    - Create graph relationships for function calls
    - Track call chains and dependencies
    """

    node_type = "call"

    def process(self, node_data: dict, context: IngestionContext) -> ProcessingResult:
        """
        Process a call node.

        Args:
            node_data: Dictionary with keys: name, file_path
            context: Shared ingestion context

        Returns:
            ProcessingResult indicating success/failure
        """
        target_name = node_data.get("name", "unknown")
        file_path = node_data.get("file_path", "")

        try:
            # Create call relationship in graph
            context.graph_store.create_call_relationship(
                repo_id=context.repo_id, file_path=file_path, target_name=target_name
            )

            logger.info(f"  -> Linked Call: {target_name}")

            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                message=f"Processed call: {target_name}",
                items_processed=1,
            )

        except Exception as e:
            logger.error(f"Failed to process call {target_name}: {e}")
            result = ProcessingResult(
                status=ProcessingStatus.FAILED,
                message=f"Failed to process call: {target_name}",
            )
            result.add_error(context=f"call to {target_name} in {file_path}", error=str(e))
            return result
