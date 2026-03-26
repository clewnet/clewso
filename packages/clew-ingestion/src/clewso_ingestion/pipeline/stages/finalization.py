"""
Finalization Stage

Flushes databases, queries actual store counts, and logs a summary.
"""

import asyncio
import logging

from ..context import IngestionContext, ProcessingResult, ProcessingStatus

logger = logging.getLogger(__name__)


def _query_qdrant_count(context: IngestionContext) -> dict[str, int]:
    """Query Qdrant for point counts (repo-filtered and total)."""
    try:
        from qdrant_client.http import models

        client = context.vector_store.client
        collection = context.vector_store.collection_name

        total = client.count(collection_name=collection).count

        repo_filter = models.Filter(
            must=[models.FieldCondition(key="repo_id", match=models.MatchValue(value=context.repo_id))]
        )
        repo_count = client.count(collection_name=collection, count_filter=repo_filter).count

        return {"qdrant_total": total, "qdrant_repo": repo_count}
    except Exception as e:
        logger.warning("[Finalization] Failed to query Qdrant counts: %s", e)
        return {}


def _query_neo4j_counts(context: IngestionContext) -> dict[str, int]:
    """Query Neo4j for node/relationship counts for this repo."""
    try:
        counts: dict[str, int] = {}
        with context.graph_store.driver.session() as session:
            for label in ("File", "CodeBlock", "Module", "Function"):
                result = session.run(
                    f"MATCH (n:{label} {{repo_id: $repo_id}}) RETURN count(n) AS c",
                    repo_id=context.repo_id,
                )
                counts[f"neo4j_{label.lower()}"] = result.single()["c"]

            result = session.run(
                """
                MATCH (a)-[r]->()
                WHERE a.repo_id = $repo_id OR a.id = $repo_id
                RETURN count(r) AS c
                """,
                repo_id=context.repo_id,
            )
            counts["neo4j_relationships"] = result.single()["c"]

        return counts
    except Exception as e:
        logger.warning("[Finalization] Failed to query Neo4j counts: %s", e)
        return {}


class FinalizationStage:
    """Final stage: flush stores, query actual counts, log summary."""

    name = "Finalization"

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        logger.info(f"[{self.name}] Finalizing ingestion")

        try:
            # Flush vector store buffer
            if context.vector_store:
                if hasattr(context.vector_store, "flush"):
                    await context.vector_store.flush()

            # Note: graph_store.close() is NOT called here — the orchestrator
            # owns the driver lifecycle.

            # Query actual store counts (I/O in threads to avoid blocking)
            qdrant_counts, neo4j_counts = await asyncio.gather(
                asyncio.to_thread(_query_qdrant_count, context),
                asyncio.to_thread(_query_neo4j_counts, context),
            )

            summary = {
                "repository": context.repo_name,
                "repo_id": context.repo_id,
                "files_discovered": len(context.files),
                "nodes_parsed": len(context.nodes),
                **qdrant_counts,
                **neo4j_counts,
            }

            logger.info(f"[{self.name}] Ingestion complete for {context.repo_id}")
            logger.info(
                "[%s]   Qdrant:  %d points (repo), %d total",
                self.name,
                summary.get("qdrant_repo", -1),
                summary.get("qdrant_total", -1),
            )
            logger.info(
                "[%s]   Neo4j:   %d files, %d code blocks, %d modules, %d functions, %d relationships",
                self.name,
                summary.get("neo4j_file", -1),
                summary.get("neo4j_codeblock", -1),
                summary.get("neo4j_module", -1),
                summary.get("neo4j_function", -1),
                summary.get("neo4j_relationships", -1),
            )

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
