"""
Parsing Stage (Async)

Parses files and extracts AST nodes with batched embedding and graph writes.

This stage processes files sequentially but batches I/O operations (embedding
API calls, graph writes) for significant throughput improvement. Tree-sitter
parsing is offloaded to a thread pool via asyncio.to_thread since it is a
CPU-bound C library call.
"""

import asyncio
import logging
from typing import Any

from ..context import FileItem, IngestionContext, ParsedNode, ProcessingResult, ProcessingStatus
from ..exceptions import ParsingError
from ..ids import make_vector_id

logger = logging.getLogger(__name__)

# Number of files to accumulate before flushing embed + graph batches
BATCH_SIZE = 50

# Maximum length for the structured file summary sent to the embedding model
_MAX_SUMMARY_LENGTH = 4000


def _extract_first_docstring(content: str) -> str:
    """Extract the first triple-quoted docstring from the start of the file.

    Only searches the first 500 characters to avoid matching triple quotes
    inside string literals or function bodies deeper in the file.
    """
    head = content[:500]
    for marker in ('"""', "'''"):
        idx = head.find(marker)
        if idx == -1:
            continue
        end = head.find(marker, idx + 3)
        if end != -1:
            return head[idx + 3 : end].strip()
    return ""


def _build_file_summary(path: str, content: str, definitions: list[dict]) -> str:
    """Build a structured file summary for higher-quality embeddings.

    Extracts imports, function/class signatures, and the first docstring
    from parsed AST definitions rather than blindly truncating raw code.
    """
    imports: list[str] = []
    signatures: list[str] = []

    for defn in definitions:
        defn_type = defn.get("type", "")
        name = defn.get("name", "")
        kind = defn.get("kind", "")

        if defn_type == "import":
            imports.append(name)
        elif defn_type == "definition" and name:
            prefix = "class" if "class" in kind else "def"
            signatures.append(f"{prefix} {name}")

    parts: list[str] = [f"File: {path}"]
    if imports:
        parts.append(f"Imports: {', '.join(imports[:20])}")
    if signatures:
        parts.append(f"Defines: {', '.join(signatures)}")

    docstring = _extract_first_docstring(content)
    if docstring:
        parts.append(docstring)

    summary = "\n".join(parts)
    return summary[:_MAX_SUMMARY_LENGTH]


class ParsingStage:
    """
    Third stage: Parse files and extract AST nodes (async).

    Implements the AsyncPipelineStage protocol. The orchestrator detects
    this via async execute() method and awaits it.

    Responsibilities:
    - Read file content (via thread pool for non-blocking I/O)
    - Parse with tree-sitter (via thread pool for CPU-bound C calls)
    - Extract definitions, imports, calls
    - Batch-vectorize file-level content via vector_store.add_batch()
    - Batch-create file nodes in graph via create_file_nodes_batch()
    """

    name = "Parsing"

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Parse all discovered files with batched I/O.

        Files are processed one at a time in the async-for loop, but embedding
        and graph operations are accumulated and flushed in batches. This avoids
        N serial embedding API calls (the primary bottleneck).

        Args:
            context: Ingestion context

        Returns:
            ProcessingResult with parsing statistics
        """
        logger.info(f"[{self.name}] Parsing {len(context.files)} files")

        files_processed = 0
        files_failed = 0
        nodes_extracted = 0
        errors: list[dict[str, str]] = []

        # Batching accumulators
        embed_batch: list[tuple[str, dict[str, Any], str | None]] = []
        graph_ops: list[tuple[str, dict[str, Any]]] = []

        async for file_item, content in self._file_reader(context.files):
            try:
                nodes_count, file_embed_item, file_graph_op = await self._process_file(file_item, content, context)
                files_processed += 1
                nodes_extracted += nodes_count

                embed_batch.append(file_embed_item)
                graph_ops.append(file_graph_op)

                logger.info(f"[{self.name}] Processed {file_item.path} ({nodes_count} nodes)")

                # Flush batch when large enough
                if len(embed_batch) >= BATCH_SIZE:
                    try:
                        await self._flush_batch(embed_batch, graph_ops, context)
                    except Exception as e:
                        logger.error(f"[{self.name}] Failed to flush batch: {e}")
                        errors.append({"context": "batch_flush", "error": str(e)})
                        files_failed += len(embed_batch)
                    finally:
                        embed_batch = []
                        graph_ops = []

            except Exception as e:
                files_failed += 1
                error_msg = str(e)
                logger.error(f"[{self.name}] Failed to process {file_item.path}: {error_msg}")
                errors.append({"context": file_item.path, "error": error_msg})

        # Final flush for remainder
        if embed_batch:
            try:
                await self._flush_batch(embed_batch, graph_ops, context)
            except Exception as e:
                logger.error(f"[{self.name}] Failed to flush final batch: {e}")
                errors.append({"context": "batch_flush_final", "error": str(e)})
                files_failed += len(embed_batch)

        # Determine overall status
        if files_failed == 0:
            status = ProcessingStatus.SUCCESS
        elif files_processed > 0:
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.FAILED

        return ProcessingResult(
            status=status,
            message=f"Parsed {files_processed} files, extracted {nodes_extracted} nodes",
            items_processed=files_processed,
            items_failed=files_failed,
            errors=errors,
            metadata={"nodes_extracted": nodes_extracted},
        )

    async def _file_reader(self, files: list[FileItem]):
        """
        Async generator that yields files with loaded content.

        File I/O is offloaded to a thread to avoid blocking the event loop.

        Args:
            files: List of FileItem objects to read

        Yields:
            (file_item, content) tuples
        """
        for file_item in files:
            content = await asyncio.to_thread(file_item.load_content)
            yield file_item, content

    async def _process_file(
        self,
        file_item: FileItem,
        content: str,
        context: IngestionContext,
    ) -> tuple[int, tuple[str, dict[str, Any], str | None], tuple[str, dict[str, Any]]]:
        """
        Process a single file: parse AST and collect batch items.

        Does NOT call vector_store or graph_store directly — instead returns
        the embed item and graph operation data for the caller to batch.

        Args:
            file_item: The file to process
            content: Pre-loaded file content
            context: Ingestion context

        Returns:
            Tuple of (nodes_count, embed_item, graph_op_data) where:
            - nodes_count: number of AST nodes extracted
            - embed_item: (text, metadata) for file-level embedding
            - graph_op_data: (file_path, metadata) for graph file node creation

        Raises:
            ParsingError: If file processing fails
        """
        try:
            content_bytes = content.encode("utf-8")

            # Parse AST in thread pool (tree-sitter is CPU-bound C code)
            definitions = await asyncio.to_thread(context.parser.parse_file, file_item.path, content_bytes)

            # Convert to ParsedNode objects
            for definition in definitions:
                definition["file_path"] = file_item.path
                node = ParsedNode(
                    type=definition.get("type", "definition"),
                    kind=definition.get("kind", "unknown"),
                    name=definition.get("name", "unknown"),
                    content=definition.get("content", ""),
                    start_line=definition.get("start_line", 0),
                    end_line=definition.get("end_line", 0),
                    file_path=file_item.path,
                )
                context.nodes.append(node)

            # Build structured file summary for embedding
            summary = _build_file_summary(file_item.path, content, definitions)

            embed_item = (
                summary,
                {
                    "path": file_item.path,
                    "repo_id": context.repo_id,
                    "type": "file",
                },
                make_vector_id(context.repo_id, file_item.path),
            )

            # Prepare graph operation data
            graph_op = (
                file_item.path,
                {
                    "repo_id": context.repo_id,
                    "file_path": file_item.path,
                },
            )

            return len(definitions), embed_item, graph_op

        except Exception as e:
            raise ParsingError(file_item.path, str(e)) from e

    async def _flush_batch(
        self,
        embed_batch: list[tuple[str, dict[str, Any], str | None]],
        graph_ops: list[tuple[str, dict[str, Any]]],
        context: IngestionContext,
    ) -> None:
        """
        Flush accumulated embed items and graph operations.

        Calls vector_store.add_batch() once for all file embeddings, then
        creates graph file nodes in a single batch call.

        The qdrant_id returned from add_batch is paired with each graph
        operation by index to wire up the File node's qdrant_id field.

        Args:
            embed_batch: List of (text, metadata) for batch embedding
            graph_ops: List of (file_path, metadata) for graph file node creation
            context: Ingestion context
        """
        # Batch embed all file summaries at once
        point_ids = await context.vector_store.add_batch(embed_batch)

        # Create file nodes in graph in one batch call
        items = [
            {"file_path": file_path, "qdrant_id": pid}
            for (file_path, meta), pid in zip(graph_ops, point_ids, strict=True)
        ]
        await asyncio.to_thread(
            context.graph_store.create_file_nodes_batch,
            repo_id=context.repo_id,
            items=items,
        )
