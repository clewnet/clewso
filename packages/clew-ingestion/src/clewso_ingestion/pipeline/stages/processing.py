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
from typing import Any

from ..context import IngestionContext, ProcessingResult, ProcessingStatus
from ..ids import make_block_id
from ..processors.registry import NodeProcessorRegistry
from ..stdlib_filter import is_stdlib_or_vendor

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 250

# ---------------------------------------------------------------------------
# Cypher query constants
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


# ---------------------------------------------------------------------------
# Shared helpers — used by both batched and per-node code paths
# ---------------------------------------------------------------------------


def _determine_status(processed: int, failed: int, errors: list[dict[str, str]]) -> ProcessingStatus:
    """Derive processing status from counters."""
    if failed == 0 and not errors:
        return ProcessingStatus.SUCCESS
    if processed > 0:
        return ProcessingStatus.PARTIAL
    return ProcessingStatus.FAILED


def _build_result(processed: int, failed: int, errors: list[dict[str, str]]) -> ProcessingResult:
    """Build a ``ProcessingResult`` from counters."""
    return ProcessingResult(
        status=_determine_status(processed, failed, errors),
        message=f"Processed {processed} nodes ({failed} failed)",
        items_processed=processed,
        items_failed=failed,
        errors=errors,
    )


def _node_to_dict(node: Any) -> dict[str, Any]:
    """Convert a ``ParsedNode`` to the dict format expected by per-node processors."""
    return {
        "type": node.type,
        "kind": node.kind,
        "name": node.name,
        "content": node.content,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "file_path": node.file_path,
    }


# ---------------------------------------------------------------------------
# Batch collector — accumulates Cypher + embedding ops for a single node
# ---------------------------------------------------------------------------


class _NodeCollector:
    """Translates parsed nodes into graph operations and embedding items."""

    @staticmethod
    def collect(
        node: Any,
        repo_id: str,
        embed_items: list[tuple[str, dict[str, Any], str]],
        graph_ops: list[tuple[str, dict[str, Any]]],
    ) -> bool:
        """Append ops for *node*. Returns False for unknown node types."""
        handler = _NODE_HANDLERS.get(node.type)
        if handler is None:
            logger.warning("[Processing] Unknown node type: %s", node.type)
            return False
        return handler(node, repo_id, embed_items, graph_ops)


def _handle_definition(node, repo_id, embed_items, graph_ops) -> bool:
    qdrant_id = make_block_id(repo_id, node.file_path, node.name, node.kind)
    embed_items.append(
        (
            node.content,
            {"path": node.file_path, "repo_id": repo_id, "name": node.name, "type": node.kind},
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
    return True


def _handle_import(node, repo_id, _embed_items, graph_ops) -> bool:
    if is_stdlib_or_vendor(node.name):
        logger.debug("[Processing] Skipping stdlib/vendor import: %s", node.name)
        return True
    graph_ops.append(
        (
            _CREATE_IMPORT_CYPHER,
            {"repo_id": repo_id, "file_path": node.file_path, "module_name": node.name},
        )
    )
    return True


def _handle_call(node, repo_id, _embed_items, graph_ops) -> bool:
    graph_ops.append(
        (
            _CREATE_CALL_CYPHER,
            {"repo_id": repo_id, "file_path": node.file_path, "target_name": node.name},
        )
    )
    return True


_NODE_HANDLERS = {
    "definition": _handle_definition,
    "import": _handle_import,
    "call": _handle_call,
}


# ---------------------------------------------------------------------------
# Flush helpers
# ---------------------------------------------------------------------------


async def _flush_batch(
    context: IngestionContext,
    embed_items: list[tuple[str, dict[str, Any], str]],
    graph_ops: list[tuple[str, dict[str, Any]]],
) -> None:
    """Flush embedding items and graph operations.

    Embedding writes are concurrent (each add_batch owns its data).
    Graph writes are serialized via ``context.graph_lock`` to avoid
    Neo4j deadlocks from concurrent transactions touching the same nodes.
    """
    embed_task = None
    if embed_items:
        embed_task = asyncio.ensure_future(context.vector_store.add_batch(embed_items))
    if graph_ops:
        async with context.graph_lock:
            await asyncio.to_thread(context.graph_store.execute_batch, graph_ops)
    if embed_task:
        await embed_task


async def _flush_vector_buffer(context: IngestionContext) -> None:
    """Flush the per-node vector buffer to the store in chunks."""
    batch_size = getattr(context.vector_store, "_batch_size", 128)
    if not isinstance(batch_size, int) or batch_size <= 0:
        batch_size = 128

    vectors = list(context.vector_buffer)
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start : start + batch_size]
        if batch:
            await context.vector_store.add_batch(batch)

    if hasattr(context.vector_store, "flush"):
        await context.vector_store.flush()
    context.vector_buffer.clear()


# ---------------------------------------------------------------------------
# ProcessingStage
# ---------------------------------------------------------------------------


class ProcessingStage:
    """Fourth stage: process AST nodes via batched or per-node path."""

    name = "Processing"

    def __init__(self, registry: NodeProcessorRegistry):
        self.registry = registry

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        """Process all extracted nodes."""
        if context.config.get("batch_processing", True):
            return await self._execute_batched(context)
        return await self._execute_per_node(context)

    # -- Batched path ------------------------------------------------------

    async def _execute_batched(self, context: IngestionContext) -> ProcessingResult:
        """Process nodes in batches for high-throughput graph + vector writes."""
        logger.info("[%s] Processing %d nodes (batched)", self.name, len(context.nodes))

        batch_size: int = context.config.get("processing_batch_size", DEFAULT_BATCH_SIZE)
        embed_items: list[tuple[str, dict[str, Any], str]] = []
        graph_ops: list[tuple[str, dict[str, Any]]] = []
        processed, failed = 0, 0
        errors: list[dict[str, str]] = []

        for node in context.nodes:
            try:
                if _NodeCollector.collect(node, context.repo_id, embed_items, graph_ops):
                    processed += 1
                else:
                    failed += 1
                    continue

                if len(graph_ops) >= batch_size:
                    await _flush_batch(context, embed_items, graph_ops)
                    embed_items, graph_ops = [], []
            except Exception as exc:
                failed += 1
                errors.append({"context": f"{node.type} {node.name} in {node.file_path}", "error": str(exc)})
                logger.error("[%s] Failed to collect node %s: %s", self.name, node.name, exc)

        if embed_items or graph_ops:
            try:
                await _flush_batch(context, embed_items, graph_ops)
            except Exception as exc:
                logger.error("[%s] Final batch flush failed: %s", self.name, exc)
                errors.append({"context": "batch_flush", "error": str(exc)})

        result = _build_result(processed, failed, errors)
        logger.info("[%s] %s", self.name, result.message)
        return result

    # -- Streaming batch entry point ----------------------------------------

    async def process_node_batch(
        self,
        nodes: list,
        context: IngestionContext,
    ) -> ProcessingResult:
        """Process a single batch of nodes (used by the pipelined orchestrator).

        Same logic as ``_execute_batched`` but for an externally supplied
        node list rather than reading from ``context.nodes``.
        """
        batch_size: int = context.config.get("processing_batch_size", DEFAULT_BATCH_SIZE)
        embed_items: list[tuple[str, dict[str, Any], str]] = []
        graph_ops: list[tuple[str, dict[str, Any]]] = []
        processed, failed = 0, 0
        errors: list[dict[str, str]] = []

        for node in nodes:
            try:
                if _NodeCollector.collect(node, context.repo_id, embed_items, graph_ops):
                    processed += 1
                else:
                    failed += 1
                    continue

                if len(graph_ops) >= batch_size:
                    await _flush_batch(context, embed_items, graph_ops)
                    embed_items, graph_ops = [], []
            except Exception as exc:
                failed += 1
                errors.append({"context": f"{node.type} {node.name} in {node.file_path}", "error": str(exc)})
                logger.error("[%s] Failed to collect node %s: %s", self.name, node.name, exc)

        if embed_items or graph_ops:
            try:
                await _flush_batch(context, embed_items, graph_ops)
            except Exception as exc:
                logger.error("[%s] Batch flush failed: %s", self.name, exc)
                errors.append({"context": "batch_flush", "error": str(exc)})

        return _build_result(processed, failed, errors)

    # -- Per-node path -----------------------------------------------------

    async def _execute_per_node(self, context: IngestionContext) -> ProcessingResult:
        """Process nodes one at a time via the processor registry."""
        logger.info("[%s] Processing %d nodes (per-node)", self.name, len(context.nodes))

        processed, failed = 0, 0
        errors: list[dict[str, str]] = []

        for node in context.nodes:
            result = self.registry.process(_node_to_dict(node), context)
            if result.is_success:
                processed += 1
            else:
                failed += 1
                errors.extend(result.errors)

        if context.vector_buffer:
            logger.info("[%s] Flushing %d vectors to store...", self.name, len(context.vector_buffer))
            try:
                await _flush_vector_buffer(context)
            except Exception as exc:
                logger.error("[%s] Failed to flush vector buffer: %s", self.name, exc)
                errors.append({"context": "vector_flush", "error": f"Vector flush failed: {exc}"})

        result = _build_result(processed, failed, errors)
        logger.info("[%s] %s", self.name, result.message)
        return result
