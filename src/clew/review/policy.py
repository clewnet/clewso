"""Policy violation checking against changed files."""

import fnmatch
import logging
from dataclasses import dataclass

from ..client import ClewAPIClient

logger = logging.getLogger("clew.review.policy")


@dataclass
class PolicyViolation:
    rule_id: str
    rule_type: str  # banned_import, protected_write, unguarded_path
    severity: str  # block, warn, audit
    message: str
    file_path: str
    matched_pattern: str


async def fetch_policies(client: ClewAPIClient) -> list[dict]:
    """Fetch active policies from the API. Returns empty list on 404."""
    try:
        response = await client.client.get("/policies")
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else data.get("policies", [])
    except Exception as e:
        logger.warning(f"Could not fetch policies (endpoint may not exist yet): {e}")
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
    violations = []

    for policy in policies:
        rule_id = policy.get("id", "unknown")
        rule_type = policy.get("type", "")
        pattern = policy.get("pattern", "")
        severity = policy.get("severity", "warn")
        message = policy.get("message", "Policy violation")

        if rule_type == "banned_import":
            # Check diff content for banned import patterns
            for fpath, diff_content in file_diffs.items():
                if _check_banned_import(diff_content, pattern):
                    violations.append(
                        PolicyViolation(
                            rule_id=rule_id,
                            rule_type=rule_type,
                            severity=severity,
                            message=message,
                            file_path=fpath,
                            matched_pattern=pattern,
                        )
                    )

        elif rule_type in ("protected_write", "unguarded_path"):
            # Check if changed file paths match the glob pattern
            for fpath in changed_files:
                if fnmatch.fnmatch(fpath, pattern):
                    violations.append(
                        PolicyViolation(
                            rule_id=rule_id,
                            rule_type=rule_type,
                            severity=severity,
                            message=message,
                            file_path=fpath,
                            matched_pattern=pattern,
                        )
                    )

    return violations


def _check_banned_import(diff_content: str, pattern: str) -> bool:
    """Check if a diff contains a banned import matching the pattern."""
    for line in diff_content.splitlines():
        # Only check added lines (lines starting with +, not +++)
        if not line.startswith("+") or line.startswith("+++"):
            continue
        line_content = line[1:].strip()
        # Check import/from statements
        if line_content.startswith(("import ", "from ")):
            # Extract the module being imported
            if fnmatch.fnmatch(line_content, f"*{pattern}*"):
                return True
    return False
