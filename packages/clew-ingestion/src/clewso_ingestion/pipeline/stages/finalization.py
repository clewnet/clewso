"""
Finalization Stage

Flushes databases and performs cleanup.
"""

import logging

from ..context import IngestionContext, ProcessingResult, ProcessingStatus

logger = logging.getLogger(__name__)


class FinalizationStage:
    """
    Final stage: Finalize ingestion.

    Responsibilities:
    - Flush vector store buffer
    - Close database connections
    - Generate summary statistics
    - Cleanup temporary resources
    """

    name = "Finalization"

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Finalize ingestion.

        Args:
            context: Ingestion context

        Returns:
            ProcessingResult with finalization status
        """
        logger.info(f"[{self.name}] Finalizing ingestion")

        try:
            # Flush vector store buffer
            if context.vector_store:
                if hasattr(context.vector_store, "flush"):
                    await context.vector_store.flush()
                logger.info(f"[{self.name}] Flushed vector store")

            # Close graph store connection
            if context.graph_store:
                context.graph_store.close()
                logger.info(f"[{self.name}] Closed graph store connection")

            # Generate summary
            summary = {
                "repository": context.repo_name,
                "files_processed": len(context.files),
                "nodes_extracted": len(context.nodes),
            }

            logger.info(f"[{self.name}] Ingestion complete!")
            logger.info(f"[{self.name}] Summary: {summary}")

            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                message="Ingestion finalized successfully",
                items_processed=1,
                metadata=summary,
            )

        except Exception as e:
            logger.error(f"[{self.name}] Finalization failed: {e}", exc_info=True)
            result = ProcessingResult(status=ProcessingStatus.FAILED, message=f"Finalization failed: {str(e)}")
            result.add_error(context="finalization", error=str(e))
            return result
