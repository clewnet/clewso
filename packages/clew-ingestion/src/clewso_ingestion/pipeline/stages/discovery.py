"""
File Discovery Stage

Walks the repository directory and discovers files to process.
"""

import logging
import os
import subprocess
from pathlib import Path

from ..context import FileItem, IngestionContext, ProcessingResult, ProcessingStatus
from ..language_registry import EXTENSION_MAP

logger = logging.getLogger(__name__)


class FileDiscoveryStage:
    """
    Second stage: Discover files to process.

    Responsibilities:
    - Prefer git-tracked files (respects .gitignore automatically)
    - Fallback to directory walk with comprehensive ignore patterns
    - Filter files by extension
    - Create FileItem objects for each discovered file
    """

    name = "FileDiscovery"

    # Supported file extensions — derived from the language registry
    # plus .md which is indexed at file-level (not tree-sitter parsed).
    SUPPORTED_EXTENSIONS = set(EXTENSION_MAP.keys()) | {".md"}

    # Comprehensive ignore patterns - always excluded even if not in .gitignore
    # Covers common cache directories, build artifacts, and local configs
    IGNORED_DIRS = {
        # Version control
        ".git",
        ".svn",
        ".hg",
        # Dependencies
        "node_modules",
        "vendor",
        "bower_components",
        # Python
        "__pycache__",
        "venv",
        ".venv",
        "env",
        ".env",
        "dist",
        "build",
        "*.egg-info",
        ".eggs",
        ".tox",
        ".nox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".pytype",
        ".hypothesis",
        # IDEs and editors
        ".idea",
        ".vscode",
        ".vs",
        ".eclipse",
        ".settings",
        "*.swp",
        "*.swo",
        "*~",
        # Build outputs
        "target",
        "out",
        "bin",
        "obj",
        # Caches and temp
        ".cache",
        ".tmp",
        "tmp",
        "temp",
        # OS metadata
        ".DS_Store",
        "Thumbs.db",
        # Project-specific (but commonly unwanted)
        ".beads",
        ".claude",
        ".cursor",
        ".next",
        ".nuxt",
        ".output",
        "coverage",
        "htmlcov",
        ".coverage",
        ".nyc_output",
    }

    # File patterns to always ignore
    IGNORED_FILES = {
        ".DS_Store",
        "Thumbs.db",
        ".mcp.json",
        ".env",
        ".env.local",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.log",
        "*.pid",
        "*.lock",
    }

    def _should_ignore_file(self, filename: str) -> bool:
        """Check if a file matches ignore patterns."""
        for pattern in self.IGNORED_FILES:
            if pattern.startswith("*"):
                if filename.endswith(pattern[1:]):
                    return True
            elif filename == pattern:
                return True
        return False

    def _discover_via_git(self, context: IngestionContext) -> list[Path] | None:
        """
        Use git ls-files to discover files (respects .gitignore automatically).

        Returns:
            List of file paths if git is available, None otherwise
        """
        git_dir = context.temp_dir / ".git"
        if not git_dir.exists():
            return None

        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=context.temp_dir,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            files = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    path = Path(line.strip())
                    if path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                        files.append(path)

            logger.info(f"[{self.name}] Using git ls-files (respects .gitignore)")
            return files

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning(f"[{self.name}] git ls-files failed: {e}, falling back to directory walk")
            return None

    def _discover_via_walk(self, context: IngestionContext) -> list[Path]:
        """
        Walk directory tree with comprehensive ignore patterns (fallback).

        Returns:
            List of file paths
        """
        files = []
        for root, dirs, filenames in os.walk(context.temp_dir):
            # Filter out ignored directories (modifies dirs in-place to prune walk)
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS]

            for filename in filenames:
                # Skip ignored files
                if self._should_ignore_file(filename):
                    continue

                ext = Path(filename).suffix.lower()
                if ext in self.SUPPORTED_EXTENSIONS:
                    full_path = Path(root) / filename
                    rel_path = full_path.relative_to(context.temp_dir)
                    files.append(rel_path)

        logger.info(f"[{self.name}] Using directory walk with ignore patterns")
        return files

    def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Discover files to process.

        Strategy:
        1. Try git ls-files first (respects .gitignore)
        2. Fallback to directory walk with comprehensive ignore list

        Args:
            context: Ingestion context

        Returns:
            ProcessingResult with discovered files count
        """
        logger.info(f"[{self.name}] Starting file discovery in {context.temp_dir}")

        # Try git first, fallback to walk
        discovered_paths = self._discover_via_git(context)
        if discovered_paths is None:
            discovered_paths = self._discover_via_walk(context)

        # Create FileItem objects
        files_found = 0
        for rel_path in discovered_paths:
            full_path = context.temp_dir / rel_path
            if full_path.exists():  # Safety check
                file_item = FileItem(
                    path=str(rel_path),
                    absolute_path=full_path,
                    metadata={"extension": rel_path.suffix.lower()},
                )
                context.files.append(file_item)
                files_found += 1

        logger.info(f"[{self.name}] Discovered {files_found} files")

        return ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            message=f"Discovered {files_found} files",
            items_processed=files_found,
        )
