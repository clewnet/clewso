"""Deterministic vector ID generation for the ingestion pipeline.

IDs are computed as sha256(repo_id + ":" + file_path) so that the same
file in the same repo always produces the same ID across ingests.  This
makes upsert idempotent and enables deletion by ID without a metadata
filter round-trip.
"""

import hashlib


def make_vector_id(repo_id: str, file_path: str) -> str:
    """Return a stable, collision-free ID for a file within a repository.

    Args:
        repo_id: Repository identifier (e.g. "owner/repo").
        file_path: Relative file path within the repository.

    Returns:
        64-character lowercase hex string (SHA-256 digest).
    """
    raw = f"{repo_id}:{file_path}"
    return hashlib.sha256(raw.encode()).hexdigest()
