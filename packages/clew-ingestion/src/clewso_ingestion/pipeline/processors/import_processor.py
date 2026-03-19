"""
Import processor for handling import statements.
"""

import logging

from ..context import IngestionContext, ProcessingResult, ProcessingStatus
from ..stdlib_filter import is_stdlib_or_vendor

logger = logging.getLogger(__name__)


class ImportProcessor:
    """
    Processes AST nodes representing import statements.

    Responsibilities:
    - Create graph relationships between files and imported modules
    - Track dependencies
    - Skip stdlib/vendor imports to reduce graph noise
    """

    node_type = "import"

    def process(self, node_data: dict, context: IngestionContext) -> ProcessingResult:
        """
        Process an import node.

        Args:
            node_data: Dictionary with keys: name, file_path
            context: Shared ingestion context

        Returns:
            ProcessingResult indicating success/failure
        """
        module_name = node_data.get("name", "unknown")
        file_path = node_data.get("file_path", "")

        # Skip stdlib and vendor imports (consistent with batched path)
        if is_stdlib_or_vendor(module_name):
            logger.debug(f"  -> Skipping stdlib/vendor import: {module_name}")
            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                message=f"Skipped stdlib import: {module_name}",
                items_processed=1,
            )

        try:
            # Create import relationship in graph
            context.graph_store.create_import_relationship(
                repo_id=context.repo_id, file_path=file_path, module_name=module_name
            )

            logger.info(f"  -> Linked Import: {module_name}")

            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                message=f"Processed import: {module_name}",
                items_processed=1,
            )

        except Exception as e:
            logger.error(f"Failed to process import {module_name}: {e}")
            result = ProcessingResult(
                status=ProcessingStatus.FAILED,
                message=f"Failed to process import: {module_name}",
            )
            result.add_error(context=f"import {module_name} in {file_path}", error=str(e))
            return result
