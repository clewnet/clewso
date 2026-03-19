"""Authentication utilities — password hashing and verification."""

import hashlib
import secrets


def hash_password(raw_password: str) -> str:
    """Generate a salted SHA-256 hash of the password."""
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}{raw_password}".encode()).hexdigest()
    return f"{salt}:{digest}"


def verify_password(raw_password: str, stored_hash: str) -> bool:
    """Check a raw password against a stored salt:hash pair."""
    if ":" not in stored_hash:
        return False
    salt, expected_digest = stored_hash.split(":", 1)
    actual_digest = hashlib.sha256(f"{salt}{raw_password}".encode()).hexdigest()
    return secrets.compare_digest(actual_digest, expected_digest)
