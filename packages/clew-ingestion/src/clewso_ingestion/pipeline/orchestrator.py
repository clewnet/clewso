"""
Ingestion Pipeline Orchestrator

Coordinates the execution of all pipeline stages.
Supports both synchronous and asynchronous stages — async stages are
detected via inspect.iscoroutinefunction(stage.execute) and awaited.
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

        # Initialize pipeline stages
        self.stages: list[PipelineStage | AsyncPipelineStage] = [
            RepositoryPreparationStage(),
            FileDiscoveryStage(),
            ParsingStage(),
            SignatureExtractionStage(),
            ProcessingStage(self.registry),
            FinalizationStage(),
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
        finally:
            pool.shutdown(wait=True)

    async def _execute_stages(self, context: IngestionContext) -> ProcessingResult:
        """
        Execute all pipeline stages sequentially.

        Async stages are awaited; sync stages are called directly.

        Args:
            context: The shared ingestion context

        Returns:
            Aggregated ProcessingResult
        """
        overall_errors: list[dict[str, str]] = []
        stage_results: list[ProcessingResult] = []

        for stage in self.stages:
            try:
                logger.info(f"Executing stage: {stage.name}")

                if inspect.iscoroutinefunction(stage.execute):
                    result = await stage.execute(context)
                else:
                    result = stage.execute(context)

                # cast: pyright can't narrow through inspect.iscoroutinefunction
                typed_result = cast(ProcessingResult, result)

                stage_results.append(typed_result)

                if typed_result.errors:
                    overall_errors.extend(typed_result.errors)

                if typed_result.status == ProcessingStatus.FAILED:
                    logger.error(f"Stage {stage.name} failed: {typed_result.message}")

            except Exception as e:
                error_msg = f"Stage {stage.name} raised exception: {str(e)}"
                logger.error(error_msg, exc_info=True)
                overall_errors.append({"context": stage.name, "error": str(e)})
                raise StageError(stage.name, str(e)) from e

        # Determine overall status
        failed_stages = sum(1 for r in stage_results if r.status == ProcessingStatus.FAILED)
        partial_stages = sum(1 for r in stage_results if r.status == ProcessingStatus.PARTIAL)

        if failed_stages > 0:
            status = ProcessingStatus.FAILED
        elif partial_stages > 0:
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.SUCCESS

        total_processed = sum(r.items_processed for r in stage_results)
        total_failed = sum(r.items_failed for r in stage_results)

        final_result = ProcessingResult(
            status=status,
            message=f"Pipeline completed: {total_processed} items processed, {total_failed} failed",
            items_processed=total_processed,
            items_failed=total_failed,
            errors=overall_errors,
            metadata={"stage_results": [r.message for r in stage_results]},
        )

        logger.info(f"Pipeline finished: {final_result.message}")

        return final_result

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
