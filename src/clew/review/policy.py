"""Policy violation checking against changed files."""

import fnmatch
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from ..client import ClewAPIClient

logger = logging.getLogger("clew.review.policy")

_POLICY_DEFAULTS: dict[str, str] = {
    "id": "unknown",
    "type": "",
    "pattern": "",
    "severity": "warn",
    "message": "Policy violation",
}

_PATH_MATCH_TYPES = frozenset(("protected_write", "unguarded_path"))


@dataclass(slots=True)
class PolicyViolation:
    rule_id: str
    rule_type: str
    severity: str
    message: str
    file_path: str
    matched_pattern: str

    @classmethod
    def from_policy(cls, policy: dict[str, str], file_path: str) -> "PolicyViolation":
        """Build a violation from a raw policy dict and the offending path."""
        return cls(
            rule_id=policy.get("id", _POLICY_DEFAULTS["id"]),
            rule_type=policy.get("type", _POLICY_DEFAULTS["type"]),
            severity=policy.get("severity", _POLICY_DEFAULTS["severity"]),
            message=policy.get("message", _POLICY_DEFAULTS["message"]),
            file_path=file_path,
            matched_pattern=policy.get("pattern", _POLICY_DEFAULTS["pattern"]),
        )


async def fetch_policies(client: ClewAPIClient | None = None) -> list[dict]:
    """Fetch active policies. Uses direct store access first, falls back to API."""
    # Try direct store access (works without server running)
    try:
        from ..config import get_config
        from ..stores import get_graph_store

        cfg = get_config()
        store = get_graph_store(cfg)
        policies = await store.get_policies()
        if policies:
            return policies
    except Exception as e:
        logger.debug("Direct policy fetch failed, trying API: %s", e)

    # Fall back to HTTP API
    if client is None:
        return []
    try:
        response = await client.client.get("policies")
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else data.get("policies", [])
    except Exception as e:
        logger.debug("API policy fetch failed: %s", e)
        return []


def check_policies(
    policies: list[dict],
    changed_files: list[str],
    file_diffs: dict[str, str],
) -> list[PolicyViolation]:
    """Check changed files against policy rules.

    Args:
        policies: List of policy dicts with keys: id, type, pattern, severity, message
        changed_files: List of changed file paths
        file_diffs: Map of file path to diff content

    Returns:
        List of PolicyViolation for any matches found
    """
    violations: list[PolicyViolation] = []
    for policy in policies:
        violations.extend(_check_single_policy(policy, changed_files, file_diffs))
    return violations


def _matching_banned_imports(policy: dict, file_diffs: dict[str, str]) -> list[PolicyViolation]:
    """Return violations for any diffs containing a banned import."""
    pattern = policy.get("pattern", "")
    return [
        PolicyViolation.from_policy(policy, fpath)
        for fpath, diff in file_diffs.items()
        if _check_banned_import(diff, pattern)
    ]


def _matching_path_rules(policy: dict, changed_files: Sequence[str]) -> list[PolicyViolation]:
    """Return violations for changed paths matching a glob pattern."""
    pattern = policy.get("pattern", "")
    return [PolicyViolation.from_policy(policy, fpath) for fpath in changed_files if fnmatch.fnmatch(fpath, pattern)]


def _check_single_policy(
    policy: dict,
    changed_files: list[str],
    file_diffs: dict[str, str],
) -> list[PolicyViolation]:
    """Evaluate one policy against the changed files and diffs."""
    rule_type = policy.get("type", "")
    if rule_type == "banned_import":
        return _matching_banned_imports(policy, file_diffs)
    if rule_type in _PATH_MATCH_TYPES:
        return _matching_path_rules(policy, changed_files)
    return []


def _check_banned_import(diff_content: str, pattern: str) -> bool:
    """Check if a diff contains a banned import matching the pattern."""
    glob_pattern = f"*{pattern}*"
    for line in diff_content.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        stripped = line[1:].strip()
        if stripped.startswith(("import ", "from ")) and fnmatch.fnmatch(stripped, glob_pattern):
            return True
    return False
