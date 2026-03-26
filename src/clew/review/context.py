import logging
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from .graph import ImpactedFile

logger = logging.getLogger("clew.review.context")

_BINARY_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".pyc", ".so", ".dll", ".exe", ".bin"})


@dataclass(slots=True)
class FileContext:
    path: str
    content: str
    token_est: int
    score: float

    @classmethod
    def from_file(cls, impact: ImpactedFile, file_path: str, repo_root: str = "") -> "FileContext | None":
        """Read a source file and wrap it as context, or return None on failure.

        If the file doesn't exist on disk (e.g. deleted in this diff),
        falls back to ``git show HEAD:<path>`` to retrieve the last
        committed version.
        """
        if _is_binary(file_path):
            logger.info("Skipping binary file: %s", impact.path)
            return None

        content = _read_file_or_git(file_path, impact.path, repo_root)
        if content is None:
            return None

        return cls(
            path=impact.path,
            content=content,
            token_est=estimate_tokens(content),
            score=impact.score,
        )


@dataclass(slots=True)
class ReviewContext:
    files: list[FileContext]
    total_tokens: int
    truncated: bool
    truncated_count: int


def estimate_tokens(text: str) -> int:
    """Rough estimation of tokens (4 chars per token)."""
    return len(text) // 4


def _read_file_or_git(file_path: str, relative_path: str, repo_root: str) -> str | None:
    """Read file from disk, falling back to git show HEAD:<path> for deleted files."""
    if os.path.exists(file_path):
        try:
            with open(file_path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except Exception as exc:
            logger.error("Error reading %s: %s", file_path, exc)
            return None

    # File deleted on disk — try last committed version
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{relative_path}"],
            capture_output=True,
            text=True,
            cwd=repo_root or None,
        )
        if result.returncode == 0 and result.stdout:
            logger.info("Read deleted file from git: %s", relative_path)
            return result.stdout
    except Exception as exc:
        logger.debug("git show failed for %s: %s", relative_path, exc)

    logger.warning("File not found (disk or git): %s", relative_path)
    return None


def _is_binary(file_path: str) -> bool:
    """Return True when the extension indicates a non-text format."""
    _, ext = os.path.splitext(file_path)
    return ext.lower() in _BINARY_EXTENSIONS


def _resolve_safe_path(impact_path: str, repo_root: str) -> str | None:
    """Resolve an impact path to an absolute path, blocking traversal attacks."""
    candidate = os.path.join(repo_root, impact_path.lstrip("/"))
    if not os.path.abspath(candidate).startswith(os.path.abspath(repo_root)):
        logger.warning("Security: Path traversal attempt blocked: %s", impact_path)
        return None
    return candidate


def _collect_within_budget(
    impacted_files: Sequence[ImpactedFile],
    repo_root: str,
    max_tokens: int,
) -> tuple[list[FileContext], int, int]:
    """Walk impacted files, reading those that fit in the token budget.

    Returns (fetched_files, total_tokens, truncated_count).
    """
    fetched: list[FileContext] = []
    total = 0
    skipped = 0

    for impact in impacted_files:
        if total >= max_tokens:
            skipped += 1
            continue

        safe_path = _resolve_safe_path(impact.path, repo_root)
        if safe_path is None:
            continue

        ctx = FileContext.from_file(impact, safe_path, repo_root=repo_root)
        if ctx is None:
            continue

        if total + ctx.token_est > max_tokens and total > 0:
            skipped += 1
            continue

        fetched.append(ctx)
        total += ctx.token_est

    return fetched, total, skipped


def fetch_review_context(
    impacted_files: list[ImpactedFile],
    repo_root: str,
    max_tokens: int = 32000,
) -> ReviewContext:
    """Fetch source code for impacted files, respecting token budget."""
    fetched, total_tokens, truncated_count = _collect_within_budget(impacted_files, repo_root, max_tokens)
    return ReviewContext(
        files=fetched,
        total_tokens=total_tokens,
        truncated=truncated_count > 0,
        truncated_count=truncated_count,
    )
