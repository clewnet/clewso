"""
Incremental Repository Sync Orchestrator

Processes only changed files from webhook events, avoiding full re-ingestion.
"""

import inspect
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from git import Repo

from .graph import GraphStore
from .parser import CodeParser
from .pipeline.context import (
    FileItem,
    IngestionContext,
)
from .pipeline.processors import CallProcessor, DefinitionProcessor, ImportProcessor
from .pipeline.processors.registry import NodeProcessorRegistry
from .pipeline.stages import FinalizationStage, ParsingStage, ProcessingStage
from .pipeline.stages.discovery import FileDiscoveryStage
from .vector import VectorStore

logger = logging.getLogger(__name__)


class IncrementalSyncOrchestrator:
    """
    Orchestrates incremental sync of repository changes.

    Instead of re-ingesting the entire repository, this processes only
    files that have changed in a specific commit.

    Architecture:
    - Reuses existing pipeline stages (Parsing, Processing, Finalization)
    - Skips Repository Preparation and File Discovery stages
    - Directly injects changed files as FileItems
    - Handles file deletions separately (removes from graph + vectors)
    - Falls back to full sync if too many files changed

    Example:
        orchestrator = IncrementalSyncOrchestrator(
            vector_store=VectorStore(),
            graph_store=GraphStore(),
            parser=CodeParser()
        )

        result = await orchestrator.sync_changes(
            repo_id="user/repo",
            repo_url="https://github.com/user/repo",
            commit_sha="abc123",
            changed_files={
                "added": ["new_file.py"],
                "modified": ["existing_file.py"],
                "removed": ["deleted_file.py"]
            }
        )
    """

    # Maximum files to process incrementally
    # If more files changed, fall back to full re-ingestion
    MAX_FILES_FOR_INCREMENTAL = 100

    def __init__(self, vector_store: VectorStore, graph_store: GraphStore, parser: CodeParser):
        """
        Initialize incremental sync orchestrator.

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

        # Initialize pipeline stages (only those we need)
        self.parsing_stage = ParsingStage()
        self.processing_stage = ProcessingStage(self.registry)
        self.finalization_stage = FinalizationStage()

    async def sync_changes(
        self,
        repo_id: str,
        repo_url: str,
        commit_sha: str,
        changed_files: dict[str, list[str]],
    ) -> dict[str, Any]:
        """
        Synchronize repository changes incrementally.

        Args:
            repo_id: Unique repository identifier
            repo_url: Repository URL (for cloning)
            commit_sha: Specific commit SHA to sync
            changed_files: Dict with "added", "modified", "removed" file lists

        Returns:
            Dict with sync results: {
                "status": "success" | "partial" | "failed",
                "files_synced": int,
                "files_removed": int,
                "errors": List[str],
                "fallback_to_full": bool
            }
        """
        added = changed_files.get("added", [])
        modified = changed_files.get("modified", [])
        removed = changed_files.get("removed", [])

        total_changes = len(added) + len(modified) + len(removed)

        logger.info(
            f"Incremental sync started for {repo_id}@{commit_sha}: "
            f"{len(added)} added, {len(modified)} modified, {len(removed)} removed"
        )

        # Check if we should fall back to full sync
        if total_changes > self.MAX_FILES_FOR_INCREMENTAL:
            logger.warning(
                f"Too many files changed ({total_changes} > {self.MAX_FILES_FOR_INCREMENTAL}), "
                "falling back to full re-ingestion"
            )
            return {
                "status": "fallback",
                "fallback_to_full": True,
                "message": f"Too many files changed ({total_changes})",
            }

        temp_dir = None
        try:
            # Step 1: Clone repository at specific commit
            temp_dir = await self._clone_at_commit(repo_url, commit_sha)

            # Step 2: Handle file deletions first
            files_removed = await self._remove_files(repo_id, removed)

            # Step 3: Process added and modified files
            files_to_process = added + modified
            files_synced, errors = await self._process_files(repo_id, repo_url, temp_dir, files_to_process)

            # Determine overall status
            if errors:
                status = "partial" if files_synced > 0 else "failed"
            else:
                status = "success"

            return {
                "status": status,
                "files_synced": files_synced,
                "files_removed": files_removed,
                "errors": errors,
                "fallback_to_full": False,
            }

        except Exception as e:
            logger.error(f"Incremental sync failed: {e}", exc_info=True)
            return {
                "status": "failed",
                "files_synced": 0,
                "files_removed": 0,
                "errors": [str(e)],
                "fallback_to_full": False,
            }

        finally:
            # Clean up temporary directory
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)

    async def _clone_at_commit(self, repo_url: str, commit_sha: str) -> Path:
        """
        Clone repository at a specific commit SHA.

        Args:
            repo_url: Repository URL
            commit_sha: Commit SHA to checkout

        Returns:
            Path to cloned repository

        Raises:
            Exception: If clone or checkout fails
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="clew_sync_"))

        logger.info(f"Cloning {repo_url} to {temp_dir}")

        try:
            # Clone the repository
            repo = Repo.clone_from(repo_url, temp_dir)

            # Checkout specific commit
            repo.git.checkout(commit_sha)

            logger.info(f"Checked out commit {commit_sha}")

            return temp_dir

        except Exception as e:
            # Clean up on failure
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise Exception(f"Failed to clone repository at commit {commit_sha}: {e}") from e

    async def _remove_files(self, repo_id: str, file_paths: list[str]) -> int:
        """
        Remove deleted files from graph and vector stores.

        Args:
            repo_id: Repository identifier
            file_paths: List of file paths to remove

        Returns:
            Number of files successfully removed
        """
        if not file_paths:
            return 0

        logger.info(f"Removing {len(file_paths)} deleted files from {repo_id}")

        removed_count = 0

        for file_path in file_paths:
            try:
                # Delete from graph store
                graph_deleted = self.graph_store.delete_file_node(repo_id, file_path)

                # Delete from vector store
                vector_deleted = self.vector_store.delete_by_filter(repo_id, file_path)

                logger.debug(f"Removed {file_path}: {graph_deleted} graph nodes, {vector_deleted} vectors")

                removed_count += 1

            except Exception as e:
                logger.error(f"Failed to remove {file_path}: {e}")

        return removed_count

    async def _process_files(
        self,
        repo_id: str,
        repo_url: str,
        temp_dir: Path,
        file_paths: list[str],
    ) -> tuple[int, list[str]]:
        """
        Process changed files through the pipeline.

        Args:
            repo_id: Repository identifier
            repo_url: Repository URL
            temp_dir: Path to cloned repository
            file_paths: List of file paths to process

        Returns:
            Tuple of (files_synced, errors)
        """
        if not file_paths:
            return 0, []

        logger.info(f"Processing {len(file_paths)} changed files")

        # Filter out unsupported file types
        supported_extensions = FileDiscoveryStage.SUPPORTED_EXTENSIONS
        filtered_files = [f for f in file_paths if Path(f).suffix.lower() in supported_extensions]

        if len(filtered_files) < len(file_paths):
            logger.debug(f"Filtered out {len(file_paths) - len(filtered_files)} unsupported files")

        # Create IngestionContext
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        context = IngestionContext(
            repo_id=repo_id,
            repo_name=repo_name,
            repo_url=repo_url,
            temp_dir=temp_dir,
            vector_store=self.vector_store,
            graph_store=self.graph_store,
            parser=self.parser,
        )

        # Create FileItem objects for changed files
        for file_path in filtered_files:
            absolute_path = temp_dir / file_path

            # Skip if file doesn't exist (race condition?)
            if not absolute_path.exists():
                logger.warning(f"File not found: {file_path}")
                continue

            file_item = FileItem(
                path=file_path,
                absolute_path=absolute_path,
                metadata={"extension": Path(file_path).suffix.lower()},
            )
            context.files.append(file_item)

        # Run pipeline stages
        return await self._run_pipeline_stages(context)

    async def _run_pipeline_stages(self, context: IngestionContext) -> tuple[int, list[str]]:
        """Helper to run pipeline stages and collect errors.

        Supports both sync and async stages via inspect.iscoroutinefunction().
        """
        errors: list[str] = []
        files_synced = 0

        stages: list[Any] = [self.parsing_stage, self.processing_stage, self.finalization_stage]

        try:
            for stage in stages:
                if inspect.iscoroutinefunction(stage.execute):
                    result = await stage.execute(context)
                else:
                    result = stage.execute(context)

                if result.errors:
                    errors.extend([e["error"] for e in result.errors])

            # Count successfully processed files
            files_synced = len(context.files) - len([e for e in errors if e])  # Rough estimate

            logger.info(f"Pipeline complete: {files_synced} files synced, {len(errors)} errors")

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}", exc_info=True)
            errors.append(str(e))

        return files_synced, errors
