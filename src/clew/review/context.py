import logging
import os
from dataclasses import dataclass

from .graph import ImpactedFile

logger = logging.getLogger("clew.review.context")


@dataclass
class FileContext:
    path: str
    content: str
    token_est: int
    score: float


@dataclass
class ReviewContext:
    files: list[FileContext]
    total_tokens: int
    truncated: bool
    truncated_count: int


def estimate_tokens(text: str) -> int:
    """Rough estimation of tokens (4 chars per token)."""
    return len(text) // 4


def fetch_review_context(impacted_files: list[ImpactedFile], repo_root: str, max_tokens: int = 32000) -> ReviewContext:
    """
    Fetches source code for the impacted files, respecting token budget.
    """
    fetched_files: list[FileContext] = []
    current_tokens = 0
    truncated = False
    truncated_count = 0

    # Binary/Non-text extensions to skip
    SKIP_EXTS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".pdf",
        ".zip",
        ".pyc",
        ".so",
        ".dll",
        ".exe",
        ".bin",
    }

    for impact in impacted_files:
        # Check limit
        if current_tokens >= max_tokens:
            truncated = True
            truncated_count += 1
            continue

        file_path = os.path.join(repo_root, impact.path.lstrip("/"))

        # Security: Prevent path traversal
        abs_path = os.path.abspath(file_path)
        if not abs_path.startswith(os.path.abspath(repo_root)):
            logger.warning(f"Security: Path traversal attempt blocked: {impact.path}")
            continue

        # 1. Skip if binary
        _, ext = os.path.splitext(file_path)
        if ext.lower() in SKIP_EXTS:
            logger.info(f"Skipping binary file: {impact.path}")
            continue

        # 2. Check existence
        if not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}")
            continue

        try:
            # 3. Read Content
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()

            tokens = estimate_tokens(content)

            if current_tokens + tokens > max_tokens and current_tokens > 0:
                truncated = True
                truncated_count += 1
                continue

            fetched_files.append(FileContext(path=impact.path, content=content, token_est=tokens, score=impact.score))
            current_tokens += tokens

        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")

    return ReviewContext(
        files=fetched_files,
        total_tokens=current_tokens,
        truncated=truncated,
        truncated_count=truncated_count,
    )
