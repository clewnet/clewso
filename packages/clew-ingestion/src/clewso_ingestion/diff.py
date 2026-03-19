"""
Compute a ChangeSet from a git diff between two commits.

Uses GitPython to diff ``from_sha`` against ``to_sha`` (defaulting to HEAD)
and categorises each entry into added, modified, or removed file lists.
"""

import logging

import git

from .pipeline.context import ChangeSet

logger = logging.getLogger(__name__)


def compute_changeset(
    repo_id: str,
    repo_path: str,
    from_sha: str,
    to_sha: str | None = None,
) -> ChangeSet:
    """Compute the file-level delta between two commits.

    Args:
        repo_id: Unique repository identifier.
        repo_path: Local filesystem path to the git repository.
        from_sha: Base commit SHA (the last indexed commit).
        to_sha: Target commit SHA.  Defaults to HEAD when ``None``.

    Returns:
        A ``ChangeSet`` ready to be fed to ``IncrementalIngestionPipeline.run()``.
    """
    repo = git.Repo(repo_path)
    base = repo.commit(from_sha)
    head = repo.commit(to_sha) if to_sha else repo.head.commit

    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []

    for diff_item in base.diff(head):
        change_type = diff_item.change_type
        a_path: str = diff_item.a_path or ""
        b_path: str = diff_item.b_path or ""

        if change_type == "A":
            added.append(b_path)
        elif change_type == "D":
            removed.append(a_path)
        elif change_type == "M":
            modified.append(b_path)
        elif change_type == "R":
            # Rename → remove old path, add new path
            removed.append(a_path)
            added.append(b_path)
        elif change_type in ("C", "T"):
            # Copy or type-change → treat as modified
            modified.append(b_path)
        else:
            logger.warning(f"Unknown diff change type '{change_type}' for {b_path}")
            modified.append(b_path)

    logger.info(f"Changeset for {repo_id}: {len(added)} added, {len(modified)} modified, {len(removed)} removed")

    return ChangeSet(
        repo_id=repo_id,
        repo_path=repo_path,
        commit_sha=head.hexsha,
        added=added,
        modified=modified,
        removed=removed,
    )
