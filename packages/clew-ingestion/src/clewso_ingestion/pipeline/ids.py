"""Deterministic vector ID generation for the ingestion pipeline.

IDs are derived from SHA-256 digests truncated to UUIDs so that the
same entity always maps to the same Qdrant point ID across ingests.
This makes upserts idempotent and enables deletion by ID without a
metadata filter round-trip.
"""

import hashlib
import uuid


def _sha_to_uuid(raw: str) -> str:
    """Hash *raw* with SHA-256 and return the first 128 bits as a UUID."""
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return str(uuid.UUID(hex=digest[:32]))


def make_vector_id(repo_id: str, file_path: str) -> str:
    """Deterministic UUID for a **file** within a repository.

    Key: ``repo_id + ":" + file_path``
    """
    return _sha_to_uuid(f"{repo_id}:{file_path}")


def make_block_id(repo_id: str, file_path: str, name: str, kind: str) -> str:
    """Deterministic UUID for a **code block** (definition) within a file.

    Key matches the Neo4j MERGE key: ``(repo_id, file_path, name, type)``.
    """
    return _sha_to_uuid(f"{repo_id}:{file_path}:{name}:{kind}")
