"""
Ingestion Pipeline Orchestrator

Coordinates the execution of all pipeline stages.

Parsing and node-processing are pipelined: the parsing stage streams
batches of parsed nodes via an async generator, and the processing
stage consumes each batch as soon as it arrives.  This eliminates the
idle window where processing waits for all files to be parsed first.
"""

import asyncio
import inspect
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

from .base import AsyncPipelineStage, PipelineStage
from .context import IngestionContext, ProcessingResult, ProcessingStatus
from .exceptions import StageError
from .processors import CallProcessor, DefinitionProcessor, ImportProcessor
from .processors.registry import NodeProcessorRegistry
from .stages import (
    FileDiscoveryStage,
    FinalizationStage,
    ParsingStage,
    ProcessingStage,
    RepositoryPreparationStage,
    SignatureExtractionStage,
)

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Main ingestion pipeline orchestrator.

    Coordinates the execution of pipeline stages in sequence:
    1. Repository Preparation
    2. File Discovery
    3. Parsing (async — batched embeddings + concurrent graph writes)
    4. Node Processing
    5. Finalization

    Example:
        from clewso_ingestion.graph import GraphStore
        from clewso_ingestion.parser import CodeParser
        from clewso_ingestion.vector import VectorStore

        pipeline = IngestionPipeline(
            vector_store=VectorStore(),
            graph_store=GraphStore(),
            parser=CodeParser(),
        )

        result = pipeline.run("repo-id", "https://github.com/user/repo")
    """

    # Thread pool configuration (overridable via context.config)
    DEFAULT_MAX_WORKERS = 4
    THREAD_NAME_PREFIX = "clew-parse"

    def __init__(self, vector_store, graph_store, parser):
        """
        Initialize the pipeline.

        Args:
            vector_store: VectorStore instance for embeddings
            graph_store: GraphStore instance for relationships
            parser: CodeParser instance for AST extraction
        """
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.parser = parser

        # Initialize node processor registry
        self.registry = NodeProcessorRegistry()
        self.registry.register("definition", DefinitionProcessor())
        self.registry.register("import", ImportProcessor())
        self.registry.register("call", CallProcessor())

        # Pipeline stages — split into phases for pipelined execution.
        self._prep_stages: list[PipelineStage | AsyncPipelineStage] = [
            RepositoryPreparationStage(),
            FileDiscoveryStage(),
        ]
        self._parsing_stage = ParsingStage()
        self._signature_stage = SignatureExtractionStage()
        self._processing_stage = ProcessingStage(self.registry)
        self._finalization_stage = FinalizationStage()

        # Legacy list kept for backward-compat introspection.
        self.stages: list[PipelineStage | AsyncPipelineStage] = [
            *self._prep_stages,
            self._parsing_stage,
            self._signature_stage,
            self._processing_stage,
            self._finalization_stage,
        ]

    def run(self, repo_id: str, repo_path_or_url: str) -> ProcessingResult:
        """
        Run the complete ingestion pipeline (sync entry point).

        Wraps the async pipeline execution in asyncio.run() so that
        callers do not need to manage an event loop.

        Args:
            repo_id: Unique identifier for the repository
            repo_path_or_url: Local directory path or remote repository URL

        Returns:
            ProcessingResult with overall pipeline status
        """
        return asyncio.run(self._run_async(repo_id, repo_path_or_url))

    async def _run_async(self, repo_id: str, repo_path_or_url: str) -> ProcessingResult:
        """
        Async implementation of the pipeline execution.

        Sets up a bounded ThreadPoolExecutor as the default asyncio executor
        (used by asyncio.to_thread in async stages) and tears it down in a
        finally block for deterministic cleanup.

        Args:
            repo_id: Unique identifier for the repository
            repo_path_or_url: Local directory path or remote repository URL

        Returns:
            ProcessingResult with overall pipeline status

        Raises:
            StageError: If a critical stage fails
        """
        context = self._create_context(repo_id, repo_path_or_url)

        logger.info(f"Starting ingestion pipeline for: {repo_path_or_url}")

        max_workers = context.config.get("max_workers", self.DEFAULT_MAX_WORKERS)
        pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=self.THREAD_NAME_PREFIX,
        )
        loop = asyncio.get_running_loop()
        loop.set_default_executor(pool)

        try:
            result = await self._execute_stages(context)

            if result.status in (ProcessingStatus.SUCCESS, ProcessingStatus.PARTIAL):
                head_sha = context.metadata.get("head_commit_sha")
                if head_sha:
                    self.graph_store.update_last_indexed_commit(repo_id, head_sha)
                    logger.info(f"Updated last_indexed_commit to {head_sha[:8]}")

            return result
        except KeyboardInterrupt:
            logger.warning("Interrupted — flushing pending writes before exit")
            raise
        finally:
            # Flush any buffered vector writes before closing connections.
            if hasattr(self.vector_store, "flush"):
                try:
                    await self.vector_store.flush()
                except Exception as e:
                    logger.warning("Failed to flush vector store on shutdown: %s", e)
            pool.shutdown(wait=False)
            if hasattr(self.graph_store, "close"):
                self.graph_store.close()

    async def _execute_stages(self, context: IngestionContext) -> ProcessingResult:
        """Execute pipeline stages with pipelined parsing → processing.

        Prep stages run first (repo clone, file discovery).  Then parsing
        streams node batches via an async generator and each batch is
        handed to the processing stage immediately — no waiting for all
        files to finish.  Signature extraction and finalization run after
        the stream is exhausted.
        """
        overall_errors: list[dict[str, str]] = []
        stage_results: list[ProcessingResult] = []

        # --- Phase 1: preparation stages (sync or async) -----------------
        for stage in self._prep_stages:
            result = await self._run_stage(stage, context)
            stage_results.append(result)
            overall_errors.extend(result.errors)
            if result.status == ProcessingStatus.FAILED:
                return self._aggregate(stage_results, overall_errors)

        # --- Phase 2: pipelined parsing → processing ----------------------
        # Node batches from parsing are processed concurrently (bounded by
        # a semaphore) so multiple OpenAI embedding requests are in-flight
        # at once.  Graph writes within _flush_batch are already serialized
        # per batch via asyncio.to_thread.
        max_concurrent = context.config.get("max_concurrent_batches", 8)
        sem = asyncio.Semaphore(max_concurrent)

        logger.info(
            "Starting pipelined parsing → processing (concurrency=%d)",
            max_concurrent,
        )
        parse_processed, parse_failed = 0, 0
        proc_processed, proc_failed = 0, 0
        parse_errors: list[dict[str, str]] = []
        proc_errors: list[dict[str, str]] = []
        inflight: list[asyncio.Task[ProcessingResult]] = []

        async def _process_batch(batch: list) -> ProcessingResult:
            async with sem:
                return await self._processing_stage.process_node_batch(batch, context)

        async for node_batch in self._parsing_stage.stream_nodes(context):
            parse_processed += len(node_batch)
            inflight.append(asyncio.create_task(_process_batch(node_batch)))

        # Await all in-flight processing tasks
        for proc_result in await asyncio.gather(*inflight, return_exceptions=True):
            if isinstance(proc_result, BaseException):
                proc_failed += 1
                proc_errors.append({"context": "batch_processing", "error": str(proc_result)})
                logger.error("Batch processing failed: %s", proc_result)
            else:
                proc_processed += proc_result.items_processed
                proc_failed += proc_result.items_failed
                proc_errors.extend(proc_result.errors)

        # Build synthetic results for the parsing and processing stages
        parse_result = ProcessingResult(
            status=ProcessingStatus.SUCCESS if parse_failed == 0 else ProcessingStatus.PARTIAL,
            message=f"Parsed {len(context.files)} files, streamed {parse_processed} nodes",
            items_processed=len(context.files),
            items_failed=parse_failed,
            errors=parse_errors,
        )
        stage_results.append(parse_result)
        overall_errors.extend(parse_errors)

        proc_status = ProcessingStatus.SUCCESS
        if proc_failed > 0 and proc_processed > 0:
            proc_status = ProcessingStatus.PARTIAL
        elif proc_failed > 0:
            proc_status = ProcessingStatus.FAILED
        proc_result_agg = ProcessingResult(
            status=proc_status,
            message=f"Processed {proc_processed} nodes ({proc_failed} failed)",
            items_processed=proc_processed,
            items_failed=proc_failed,
            errors=proc_errors,
        )
        stage_results.append(proc_result_agg)
        overall_errors.extend(proc_errors)

        # --- Phase 3: signature extraction + finalization -----------------
        for stage in [self._signature_stage, self._finalization_stage]:
            result = await self._run_stage(stage, context)
            stage_results.append(result)
            overall_errors.extend(result.errors)

        return self._aggregate(stage_results, overall_errors)

    async def _run_stage(
        self, stage: PipelineStage | AsyncPipelineStage, context: IngestionContext
    ) -> ProcessingResult:
        """Run a single stage, handling both sync and async execute methods."""
        try:
            logger.info(f"Executing stage: {stage.name}")
            if inspect.iscoroutinefunction(stage.execute):
                result = await stage.execute(context)
            else:
                result = stage.execute(context)
            typed = cast(ProcessingResult, result)
            if typed.status == ProcessingStatus.FAILED:
                logger.error(f"Stage {stage.name} failed: {typed.message}")
            return typed
        except Exception as e:
            logger.error(f"Stage {stage.name} raised exception: {e}", exc_info=True)
            raise StageError(stage.name, str(e)) from e

    @staticmethod
    def _aggregate(results: list[ProcessingResult], errors: list[dict[str, str]]) -> ProcessingResult:
        """Build an aggregate ProcessingResult from stage results."""
        failed = sum(1 for r in results if r.status == ProcessingStatus.FAILED)
        partial = sum(1 for r in results if r.status == ProcessingStatus.PARTIAL)

        if failed > 0:
            status = ProcessingStatus.FAILED
        elif partial > 0:
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.SUCCESS

        total_processed = sum(r.items_processed for r in results)
        total_failed = sum(r.items_failed for r in results)

        final = ProcessingResult(
            status=status,
            message=f"Pipeline completed: {total_processed} items processed, {total_failed} failed",
            items_processed=total_processed,
            items_failed=total_failed,
            errors=errors,
            metadata={"stage_results": [r.message for r in results]},
        )
        logger.info(f"Pipeline finished: {final.message}")
        return final

    def _create_context(self, repo_id: str, repo_path_or_url: str) -> IngestionContext:
        """
        Create ingestion context from repository path/URL.

        Args:
            repo_id: Unique identifier for the repository
            repo_path_or_url: Repository path or URL

        Returns:
            IngestionContext initialized with repository info
        """
        # Extract repository name
        if Path(repo_path_or_url).is_dir():
            repo_name = Path(repo_path_or_url).name
        else:
            repo_name = repo_path_or_url.split("/")[-1].replace(".git", "")

        context = IngestionContext(
            repo_id=repo_id,
            repo_name=repo_name,
            repo_url=repo_path_or_url,
            temp_dir=Path(repo_path_or_url),  # Will be updated by RepositoryPreparationStage
            vector_store=self.vector_store,
            graph_store=self.graph_store,
            parser=self.parser,
        )

        # Create repo node in graph
        self.graph_store.create_repo_node(repo_id, repo_name, repo_path_or_url)

        return context
