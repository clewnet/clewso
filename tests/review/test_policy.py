"""Tests for policy violation checking."""

from clew.review.policy import _check_banned_import, check_policies


def test_check_banned_import_matches_added_line():
    diff = """+import os.system
+from subprocess import call
 import json
"""
    assert _check_banned_import(diff, "os.system") is True


def test_check_banned_import_ignores_context_lines():
    diff = """ import os.system
-import os.system
"""
    assert _check_banned_import(diff, "os.system") is False


def test_check_banned_import_no_match():
    diff = """+import json
+from pathlib import Path
"""
    assert _check_banned_import(diff, "os.system") is False


def test_check_policies_banned_import():
    policies = [
        {
            "id": "no-subprocess",
            "type": "banned_import",
            "pattern": "subprocess",
            "severity": "block",
            "message": "Do not use subprocess",
        }
    ]
    file_diffs = {"src/foo.py": "+from subprocess import call\n import json\n"}
    violations = check_policies(policies, ["src/foo.py"], file_diffs)
    assert len(violations) == 1
    assert violations[0].rule_id == "no-subprocess"
    assert violations[0].severity == "block"
    assert violations[0].file_path == "src/foo.py"


def test_check_policies_protected_write():
    policies = [
        {
            "id": "protect-auth",
            "type": "protected_write",
            "pattern": "src/auth/*.py",
            "severity": "warn",
            "message": "Changes to auth require review",
        }
    ]
    violations = check_policies(policies, ["src/auth/login.py", "src/utils.py"], {})
    assert len(violations) == 1
    assert violations[0].file_path == "src/auth/login.py"
    assert violations[0].severity == "warn"


def test_check_policies_no_violations():
    policies = [
        {
            "id": "no-subprocess",
            "type": "banned_import",
            "pattern": "subprocess",
            "severity": "block",
            "message": "No subprocess",
        }
    ]
    file_diffs = {"src/foo.py": "+import json\n"}
    violations = check_policies(policies, ["src/foo.py"], file_diffs)
    assert len(violations) == 0


def test_check_policies_empty_policies():
    violations = check_policies([], ["src/foo.py"], {"src/foo.py": "+import os\n"})
    assert violations == []
