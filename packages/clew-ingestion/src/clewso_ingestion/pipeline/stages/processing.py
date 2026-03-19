"""
Processing Stage

Processes AST nodes using registered node processors.

Supports two code paths:
- **Batched (default):** Collects Cypher operations and embedding items across
  nodes, flushing them in configurable-size batches via ``GraphStore.execute_batch()``
  and ``VectorStore.add_batch()``.  This replaces N individual sessions with a
  small number of batched transactions for a ~10x graph-write speedup.
- **Per-node (fallback):** Delegates to the ``NodeProcessorRegistry``, which
  dispatches each node to its individual processor.  This path is still used by
  the incremental sync orchestrator (``sync.py``) and can be forced by setting
  ``context.config["batch_processing"] = False``.
"""

import asyncio
import logging
import uuid
from typing import Any

from ..context import IngestionContext, ProcessingResult, ProcessingStatus
from ..processors.registry import NodeProcessorRegistry
from ..stdlib_filter import is_stdlib_or_vendor

logger = logging.getLogger(__name__)

# Default batch size for batched processing path
DEFAULT_BATCH_SIZE = 50

# ---------------------------------------------------------------------------
# Cypher query constants — mirrors the queries in GraphStore's individual
# create_* methods so both code paths produce identical graph structures.
# ---------------------------------------------------------------------------

_CREATE_CODE_NODE_CYPHER = """
MATCH (f:File {repo_id: $repo_id, path: $file_path})
MERGE (c:CodeBlock {
    name: $name,
    type: $node_type,
    file_path: $file_path,
    repo_id: $repo_id
})
SET c.start_line = $start_line,
    c.end_line = $end_line,
    c.qdrant_id = $qdrant_id
MERGE (f)-[:DEFINES]->(c)
"""

_CREATE_IMPORT_CYPHER = """
MATCH (f:File {repo_id: $repo_id, path: $file_path})
MERGE (m:Module {name: $module_name, repo_id: $repo_id})
MERGE (f)-[:IMPORTS]->(m)
"""

_CREATE_CALL_CYPHER = """
MATCH (f:File {repo_id: $repo_id, path: $file_path})
MERGE (t:Function {name: $target_name, repo_id: $repo_id})
MERGE (f)-[:CALLS]->(t)
"""


class ProcessingStage:
    """
    Fourth stage: Process AST nodes.

    Responsibilities:
    - Iterate through extracted nodes
    - Batch embedding and graph operations for throughput
    - Fall back to per-node processors when batching is disabled
    - Handle errors gracefully
    """

    name = "Processing"

    def __init__(self, registry: NodeProcessorRegistry):
        """
        Initialize processing stage.

        Args:
            registry: Node processor registry with registered processors
        """
        self.registry = registry

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Process all extracted nodes.

        Uses the batched path by default.  Set
        ``context.config["batch_processing"] = False`` to use the per-node
        registry path instead.

        Args:
            context: Ingestion context

        Returns:
            ProcessingResult with processing statistics
        """
        use_batched = context.config.get("batch_processing", True)

        if use_batched:
            return await self._execute_batched(context)
        return await self._execute_per_node(context)

    # ------------------------------------------------------------------
    # Batched code path
    # ------------------------------------------------------------------

    async def _execute_batched(self, context: IngestionContext) -> ProcessingResult:
        """Process nodes in batches for high-throughput graph + vector writes."""
        logger.info(f"[{self.name}] Processing {len(context.nodes)} nodes (batched)")

        batch_size: int = context.config.get("processing_batch_size", DEFAULT_BATCH_SIZE)

        embed_items: list[tuple[str, dict[str, Any], str]] = []
        graph_ops: list[tuple[str, dict[str, Any]]] = []

        nodes_processed = 0
        nodes_failed = 0
        errors: list[dict[str, str]] = []

        for node in context.nodes:
            try:
                success = self._collect_node_operations(node, context.repo_id, embed_items, graph_ops)
                if not success:
                    nodes_failed += 1
                    continue

                nodes_processed += 1

                # Flush when batch is large enough
                if len(graph_ops) >= batch_size:
                    await self._flush_batch(context, embed_items, graph_ops)
                    embed_items = []
                    graph_ops = []

            except Exception as e:
                nodes_failed += 1
                errors.append(
                    {
                        "context": f"{node.type} {node.name} in {node.file_path}",
                        "error": str(e),
                    }
                )
                logger.error(f"[{self.name}] Failed to collect node {node.name}: {e}")

        # Final flush for remainder
        if embed_items or graph_ops:
            try:
                await self._flush_batch(context, embed_items, graph_ops)
            except Exception as e:
                logger.error(f"[{self.name}] Final batch flush failed: {e}")
                errors.append({"context": "batch_flush", "error": str(e)})
                if nodes_processed > 0:
                    # Downgrade to partial since some data may have been flushed
                    pass  # status logic below handles this

        # Determine overall status
        status = self._determine_status(nodes_failed, nodes_processed, errors)

        result = ProcessingResult(
            status=status,
            message=f"Processed {nodes_processed} nodes ({nodes_failed} failed)",
            items_processed=nodes_processed,
            items_failed=nodes_failed,
            errors=errors,
        )

        logger.info(f"[{self.name}] {result.message}")
        return result

    def _collect_node_operations(
        self,
        node: Any,
        repo_id: str,
        embed_items: list[tuple[str, dict[str, Any], str]],
        graph_ops: list[tuple[str, dict[str, Any]]],
    ) -> bool:
        """Collect embedding items and graph operations for a single node.

        Returns True if the node was successfully collected, False otherwise.
        """
        if node.type == "definition":
            qdrant_id = str(uuid.uuid4())
            embed_items.append(
                (
                    node.content,
                    {
                        "path": node.file_path,
                        "repo_id": repo_id,
                        "name": node.name,
                        "type": node.kind,
                    },
                    qdrant_id,
                )
            )
            graph_ops.append(
                (
                    _CREATE_CODE_NODE_CYPHER,
                    {
                        "repo_id": repo_id,
                        "file_path": node.file_path,
                        "name": node.name,
                        "node_type": node.kind,
                        "start_line": node.start_line,
                        "end_line": node.end_line,
                        "qdrant_id": qdrant_id,
                    },
                )
            )
        elif node.type == "import":
            if is_stdlib_or_vendor(node.name):
                logger.debug(f"[{self.name}] Skipping stdlib/vendor import: {node.name}")
                return True  # Not a failure, just filtered
            graph_ops.append(
                (
                    _CREATE_IMPORT_CYPHER,
                    {
                        "repo_id": repo_id,
                        "file_path": node.file_path,
                        "module_name": node.name,
                    },
                )
            )
        elif node.type == "call":
            graph_ops.append(
                (
                    _CREATE_CALL_CYPHER,
                    {
                        "repo_id": repo_id,
                        "file_path": node.file_path,
                        "target_name": node.name,
                    },
                )
            )
        else:
            logger.warning(f"[{self.name}] Unknown node type: {node.type}")
            return False
        return True

    def _determine_status(
        self, nodes_failed: int, nodes_processed: int, errors: list[dict[str, str]]
    ) -> ProcessingStatus:
        """Determine overall processing status based on failure counts."""
        if nodes_failed == 0 and not errors:
            return ProcessingStatus.SUCCESS
        elif nodes_processed > 0:
            return ProcessingStatus.PARTIAL
        else:
            return ProcessingStatus.FAILED

    async def _flush_batch(
        self,
        context: IngestionContext,
        embed_items: list[tuple[str, dict[str, Any], str]],
        graph_ops: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Flush a batch of embedding items and graph operations."""
        if embed_items:
            await context.vector_store.add_batch(embed_items)

        if graph_ops:
            await asyncio.to_thread(context.graph_store.execute_batch, graph_ops)

    # ------------------------------------------------------------------
    # Per-node code path (fallback / used by incremental sync)
    # ------------------------------------------------------------------

    async def _execute_per_node(self, context: IngestionContext) -> ProcessingResult:
        """Process nodes one at a time via the processor registry."""
        logger.info(f"[{self.name}] Processing {len(context.nodes)} nodes (per-node)")

        nodes_processed = 0
        nodes_failed = 0
        errors: list[dict[str, str]] = []

        for node in context.nodes:
            node_data = {
                "type": node.type,
                "kind": node.kind,
                "name": node.name,
                "content": node.content,
                "start_line": node.start_line,
                "end_line": node.end_line,
                "file_path": node.file_path,
            }

            result = self.registry.process(node_data, context)

            if result.is_success:
                nodes_processed += 1
            else:
                nodes_failed += 1
                errors.extend(result.errors)

        # Determine overall status
        if nodes_failed == 0:
            status = ProcessingStatus.SUCCESS
        elif nodes_processed > 0:
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.FAILED

        # Flush vector buffer (used by per-node processors)
        if context.vector_buffer:
            logger.info(f"[{self.name}] Flushing {len(context.vector_buffer)} vectors to store...")
            try:
                await self._flush_vector_buffer(context)

            except Exception as e:
                logger.error(f"[{self.name}] Failed to flush vector buffer: {e}")
                errors.append({"context": "vector_flush", "error": f"Vector flush failed: {e}"})
                # Adjust status if flush failed
                if nodes_processed > 0:
                    status = ProcessingStatus.PARTIAL
                else:
                    status = ProcessingStatus.FAILED

        result = ProcessingResult(
            status=status,
            message=f"Processed {nodes_processed} nodes ({nodes_failed} failed)",
            items_processed=nodes_processed,
            items_failed=nodes_failed,
            errors=errors,
        )

        logger.info(f"[{self.name}] {result.message}")
        return result

    async def _flush_vector_buffer(self, context: IngestionContext) -> None:
        """Flush the vector buffer to the store in chunks."""
        batch_size = getattr(context.vector_store, "_batch_size", 128)
        if not isinstance(batch_size, int) or batch_size <= 0:
            batch_size = 128

        vectors = list(context.vector_buffer)

        for start in range(0, len(vectors), batch_size):
            end = start + batch_size
            batch = vectors[start:end]
            if not batch:
                continue
            await context.vector_store.add_batch(batch)

        # Final flush to ensure persistence
        if hasattr(context.vector_store, "flush"):
            await context.vector_store.flush()

        context.vector_buffer.clear()
