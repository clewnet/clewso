"""
Repository Preparation Stage

Handles cloning remote repositories or validating local directories.
"""

import logging
import shutil
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

from ..context import IngestionContext, ProcessingResult, ProcessingStatus
from ..exceptions import RepositoryError

logger = logging.getLogger(__name__)


class RepositoryPreparationStage:
    """
    First stage in the pipeline: Prepare the repository for ingestion.

    Responsibilities:
    - Clone remote repositories to temporary directory
    - Validate local directories
    - Set up context.temp_dir
    - Extract repository metadata
    """

    name = "RepositoryPreparation"

    def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Prepare repository for ingestion.

        Args:
            context: Ingestion context

        Returns:
            ProcessingResult indicating success/failure
        """
        logger.info(f"[{self.name}] Starting repository preparation")

        try:
            # Check if local directory
            if context.is_local_repo:
                return self._prepare_local_repo(context)
            else:
                return self._clone_remote_repo(context)

        except Exception as e:
            logger.error(f"[{self.name}] Failed: {e}", exc_info=True)
            raise RepositoryError(f"Repository preparation failed: {str(e)}") from e

    def _prepare_local_repo(self, context: IngestionContext) -> ProcessingResult:
        """Validate and prepare a local repository."""
        repo_path = Path(context.repo_url)

        if not repo_path.exists():
            raise RepositoryError(f"Local path does not exist: {repo_path}")

        if not repo_path.is_dir():
            raise RepositoryError(f"Path is not a directory: {repo_path}")

        # Update context with validated path
        context.temp_dir = repo_path
        self._extract_head_sha(context, repo_path)
        logger.info(f"[{self.name}] Using local directory: {repo_path}")

        return ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            message=f"Local repository validated: {repo_path}",
            items_processed=1,
        )

    def _clone_remote_repo(self, context: IngestionContext) -> ProcessingResult:
        """Clone a remote repository."""
        temp_dir = Path(f"/tmp/oce_ingest/{context.repo_name}")

        # Clean up existing directory
        if temp_dir.exists():
            logger.info(f"[{self.name}] Removing existing directory: {temp_dir}")
            shutil.rmtree(temp_dir)

        logger.info(f"[{self.name}] Cloning {context.repo_url} to {temp_dir}")

        try:
            git_repo = Repo.clone_from(context.repo_url, temp_dir)
        except Exception as e:
            raise RepositoryError(f"Failed to clone repository: {str(e)}") from e

        # Update context
        context.temp_dir = temp_dir
        self._extract_head_sha(context, temp_dir, git_repo=git_repo)
        logger.info(f"[{self.name}] Clone complete")

        return ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            message=f"Repository cloned to: {temp_dir}",
            items_processed=1,
        )

    def _extract_head_sha(self, context: IngestionContext, repo_path: Path, *, git_repo: Repo | None = None) -> None:
        """Extract HEAD commit SHA into context.metadata, if possible."""
        try:
            if git_repo is None:
                git_repo = Repo(repo_path)
            context.metadata["head_commit_sha"] = git_repo.head.commit.hexsha
        except (InvalidGitRepositoryError, ValueError):
            logger.warning("Not a git repository or no commits — skipping SHA tracking")
