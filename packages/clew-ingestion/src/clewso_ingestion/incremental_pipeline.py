"""
IncrementalIngestionPipeline

Processes a ChangeSet (added, modified, removed files) against a repository
that is already checked out locally at the target commit.  No cloning is
performed here — that is the caller's responsibility.

Processing order:
  1. Removals first  — clean state before any additions or modifications.
  2. Additions       — new files through standard pipeline stages.
  3. Modifications   — delete outgoing graph edges, then re-process like adds.
"""

import asyncio
import logging
from pathlib import Path

from .graph import GraphStore
from .parser import CodeParser
from .pipeline.context import (
    ChangeSet,
    FileItem,
    IngestionContext,
    ProcessingResult,
    ProcessingStatus,
)
from .pipeline.ids import make_vector_id
from .pipeline.processors import CallProcessor, DefinitionProcessor, ImportProcessor
from .pipeline.processors.registry import NodeProcessorRegistry
from .pipeline.stages import FinalizationStage, ParsingStage, ProcessingStage
from .pipeline.stages.discovery import FileDiscoveryStage
from .vector import VectorStore

logger = logging.getLogger(__name__)


class IncrementalIngestionPipeline:
    """Process a ChangeSet against a locally checked-out repository.

    Unlike ``IncrementalSyncOrchestrator``, this class does not clone the
    repository.  The caller must ensure the repo is checked out at the
    commit referenced by the changeset before calling ``run()``.

    Example::

        pipeline = IncrementalIngestionPipeline(
            vector_store=VectorStore(),
            graph_store=GraphStore(),
            parser=CodeParser(),
        )
        changeset = ChangeSet(
            repo_id="owner/repo",
            repo_path="/tmp/my-checkout",
            commit_sha="abc123",
            added=["src/new.py"],
            modified=["src/old.py"],
            removed=["src/gone.py"],
        )
        result = pipeline.run(changeset)
    """

    def __init__(
        self,
        vector_store: VectorStore,
        graph_store: GraphStore,
        parser: CodeParser,
    ) -> None:
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.parser = parser

        registry = NodeProcessorRegistry()
        registry.register("definition", DefinitionProcessor())
        registry.register("import", ImportProcessor())
        registry.register("call", CallProcessor())

        self._parsing_stage = ParsingStage()
        self._processing_stage = ProcessingStage(registry)
        self._finalization_stage = FinalizationStage()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, changeset: ChangeSet) -> ProcessingResult:
        """Synchronous entry point — wraps the async implementation.

        Args:
            changeset: The set of changes to process.

        Returns:
            A ``ProcessingResult`` summarising what was done.
        """
        return asyncio.run(self._run_async(changeset))

    # ------------------------------------------------------------------
    # Async implementation
    # ------------------------------------------------------------------

    async def _run_async(self, changeset: ChangeSet) -> ProcessingResult:
        errors: list[dict[str, str]] = []
        files_synced = 0
        files_removed = 0

        repo_path = Path(changeset.repo_path)

        # 1. Removals — must happen before adds so that a rename (remove + add)
        #    leaves the graph in a clean state.
        for file_path in changeset.removed:
            try:
                await asyncio.to_thread(
                    self.graph_store.delete_file_node,
                    changeset.repo_id,
                    file_path,
                )
                await self.vector_store.delete(make_vector_id(changeset.repo_id, file_path))
                files_removed += 1
            except Exception as e:
                logger.error(f"Failed to remove {file_path}: {e}")
                errors.append({"context": file_path, "error": str(e)})

        # 2. Additions — straightforward re-parse and upsert.
        if changeset.added:
            add_result = await self._process_files(changeset, repo_path, changeset.added)
            files_synced += add_result.items_processed
            errors.extend(add_result.errors)

        # 3. Modifications — delete stale outgoing edges, then re-parse.
        if changeset.modified:
            for file_path in changeset.modified:
                try:
                    await asyncio.to_thread(
                        self.graph_store.delete_file_edges,
                        changeset.repo_id,
                        file_path,
                    )
                except Exception as e:
                    logger.warning(f"Failed to clear edges for {file_path}: {e}")

            mod_result = await self._process_files(changeset, repo_path, changeset.modified)
            files_synced += mod_result.items_processed
            errors.extend(mod_result.errors)

        # Flush any remaining vectors
        try:
            await self.vector_store.flush()
        except Exception as e:
            logger.warning(f"Vector store flush failed: {e}")

        if not errors:
            status = ProcessingStatus.SUCCESS
        elif files_synced > 0 or files_removed > 0:
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.FAILED

        return ProcessingResult(
            status=status,
            message=(f"Incremental sync: {files_synced} synced, {files_removed} removed, {len(errors)} errors"),
            items_processed=files_synced,
            items_failed=len(errors),
            errors=errors,
            metadata={
                "files_removed": files_removed,
                "commit_sha": changeset.commit_sha,
            },
        )

    async def _process_files(
        self,
        changeset: ChangeSet,
        repo_path: Path,
        file_paths: list[str],
    ) -> ProcessingResult:
        """Run a list of files through the parsing and processing stages."""
        if not file_paths:
            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                message="No files to process",
            )

        supported = FileDiscoveryStage.SUPPORTED_EXTENSIONS
        filtered = [fp for fp in file_paths if Path(fp).suffix.lower() in supported]

        context = IngestionContext(
            repo_id=changeset.repo_id,
            repo_name=changeset.repo_id.split("/")[-1],
            repo_url=changeset.repo_path,
            temp_dir=repo_path,
            vector_store=self.vector_store,
            graph_store=self.graph_store,
            parser=self.parser,
        )

        for file_path in filtered:
            abs_path = repo_path / file_path
            if not abs_path.exists():
                logger.warning(f"File not found at expected path: {file_path}")
                continue
            context.files.append(
                FileItem(
                    path=file_path,
                    absolute_path=abs_path,
                    metadata={"extension": Path(file_path).suffix.lower()},
                )
            )

        if not context.files:
            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                message="No supported files found",
            )

        errors: list[dict[str, str]] = []
        # Run parsing and processing stages only (finalization is handled
        # at the top level to avoid closing shared store connections).
        for stage in [self._parsing_stage, self._processing_stage]:
            stage_result = await stage.execute(context)
            errors.extend(stage_result.errors)

        items_processed = max(len(context.files) - len(errors), 0)
        if not errors:
            status = ProcessingStatus.SUCCESS
        elif items_processed > 0:
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.FAILED

        return ProcessingResult(
            status=status,
            message=f"Processed {items_processed} files, {len(errors)} errors",
            items_processed=items_processed,
            items_failed=len(errors),
            errors=errors,
        )
