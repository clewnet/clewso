"""
Definition processor for handling function and class definitions.
"""

import logging

from ..context import IngestionContext, ProcessingResult, ProcessingStatus

logger = logging.getLogger(__name__)


class DefinitionProcessor:
    """
    Processes AST nodes representing code definitions (functions, classes, methods).

    Responsibilities:
    - Vectorize the definition content
    - Create graph nodes for the definition
    - Link definitions to their containing files
    """

    node_type = "definition"

    def process(self, node_data: dict, context: IngestionContext) -> ProcessingResult:
        """
        Process a definition node.

        Args:
            node_data: Dictionary with keys: name, kind, content, start_line, end_line, file_path
            context: Shared ingestion context

        Returns:
            ProcessingResult indicating success/failure
        """
        name = node_data.get("name", "unknown")
        kind = node_data.get("kind", "unknown")
        content = node_data.get("content", "")
        start_line = node_data.get("start_line", 0)
        end_line = node_data.get("end_line", 0)
        file_path = node_data.get("file_path", "")

        try:
            from ..ids import make_block_id

            # Deterministic ID matching the Neo4j MERGE key
            block_qdrant_id = make_block_id(context.repo_id, file_path, name, kind)

            context.vector_buffer.append(
                (
                    content,
                    {
                        "path": file_path,
                        "repo_id": context.repo_id,
                        "name": name,
                        "type": kind,
                    },
                    block_qdrant_id,
                )
            )

            # Create graph node
            context.graph_store.create_code_node(
                repo_id=context.repo_id,
                file_path=file_path,
                name=name,
                node_type=kind,
                start_line=start_line,
                end_line=end_line,
                qdrant_id=block_qdrant_id,
            )

            logger.info(f"  -> Analyzed {kind}: {name}")

            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                message=f"Processed definition: {name}",
                items_processed=1,
            )

        except Exception as e:
            logger.error(f"Failed to process definition {name}: {e}")
            result = ProcessingResult(
                status=ProcessingStatus.FAILED,
                message=f"Failed to process definition: {name}",
            )
            result.add_error(context=f"{kind} {name} in {file_path}", error=str(e))
            return result
