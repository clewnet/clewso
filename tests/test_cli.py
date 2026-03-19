"""
Unit tests for core CLI utilities.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from clew.cli import app, get_file_diffs

runner = CliRunner()


def test_get_file_diffs_parses_diff_content():
    """Verify get_file_diffs extracts content from git diff."""
    diff = """diff --git a/src/foo.py b/src/foo.py
index 1234567..abcdefg 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 def foo():
+    print("new line")
     pass
"""
    result = get_file_diffs(diff)

    assert "src/foo.py" in result
    # New implementation returns the full diff section as a string
    assert 'print("new line")' in result["src/foo.py"]
    assert "def foo():" in result["src/foo.py"]


def test_get_file_diffs_handles_multiple_files():
    """Verify get_file_diffs handles multiple files in a single diff."""
    diff = """diff --git a/src/foo.py b/src/foo.py
index 1234567..abcdefg 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
+# New comment
 def foo():
     pass
diff --git a/src/bar.py b/src/bar.py
index 7654321..gfedcba 100644
--- a/src/bar.py
+++ b/src/bar.py
@@ -1,2 +1,3 @@
 def bar():
+    return True
"""
    result = get_file_diffs(diff)

    assert "src/foo.py" in result
    assert "src/bar.py" in result
    assert "# New comment" in result["src/foo.py"]
    assert "return True" in result["src/bar.py"]


# --- index command tests ---


def _make_mock_ingest_module(ingest_return=0, incremental_return=0):
    """Create a mock clewso_ingestion.ingest module."""
    mod = MagicMock()
    mod.ingest_repo = MagicMock(return_value=ingest_return)
    mod.ingest_repo_incremental = MagicMock(return_value=incremental_return)
    return mod


def test_index_invalid_path_exits_1():
    result = runner.invoke(app, ["index", "/nonexistent/path/abc123"])
    assert result.exit_code == 1
    assert "not a valid directory" in result.output


def test_index_full_mode_calls_ingest_repo(tmp_path):
    mock_mod = _make_mock_ingest_module()
    with patch.dict(sys.modules, {"clewso_ingestion": MagicMock(), "clewso_ingestion.ingest": mock_mod}):
        result = runner.invoke(app, ["index", str(tmp_path)])

    assert result.exit_code == 0
    mock_mod.ingest_repo.assert_called_once()
    mock_mod.ingest_repo_incremental.assert_not_called()


def test_index_incremental_mode_calls_ingest_incremental(tmp_path):
    mock_mod = _make_mock_ingest_module()
    with patch.dict(sys.modules, {"clewso_ingestion": MagicMock(), "clewso_ingestion.ingest": mock_mod}):
        result = runner.invoke(app, ["index", str(tmp_path), "--incremental"])

    assert result.exit_code == 0
    mock_mod.ingest_repo_incremental.assert_called_once()
    mock_mod.ingest_repo.assert_not_called()


def test_index_repo_id_forwarded(tmp_path):
    mock_mod = _make_mock_ingest_module()
    with patch.dict(sys.modules, {"clewso_ingestion": MagicMock(), "clewso_ingestion.ingest": mock_mod}):
        result = runner.invoke(app, ["index", str(tmp_path), "--repo-id", "my-repo"])

    assert result.exit_code == 0
    call_args = mock_mod.ingest_repo.call_args
    assert call_args[0][0] == "my-repo"


def test_index_repo_id_forwarded_incremental(tmp_path):
    mock_mod = _make_mock_ingest_module()
    with patch.dict(sys.modules, {"clewso_ingestion": MagicMock(), "clewso_ingestion.ingest": mock_mod}):
        result = runner.invoke(app, ["index", str(tmp_path), "--repo-id", "my-repo", "--incremental"])

    assert result.exit_code == 0
    call_args = mock_mod.ingest_repo_incremental.call_args
    assert call_args[0][0] == "my-repo"


# --- CLEW_WRITE_MODE tests ---


def test_index_ci_only_blocks_without_token(tmp_path):
    """ci-only write mode blocks indexing when CLEW_CI_TOKEN is not set."""
    from clew.config import reset_config

    env = {"CLEW_WRITE_MODE": "ci-only"}
    with patch.dict(os.environ, env):
        # Ensure CLEW_CI_TOKEN is unset
        os.environ.pop("CLEW_CI_TOKEN", None)
        reset_config()  # Force config reload with new env
        result = runner.invoke(app, ["index", str(tmp_path)])
    reset_config()  # Clean up

    assert result.exit_code == 1
    assert "ci-only" in result.output
    assert "CLEW_CI_TOKEN" in result.output


def test_index_ci_only_allows_with_token(tmp_path):
    """ci-only write mode allows indexing when CLEW_CI_TOKEN is set."""
    env = {"CLEW_WRITE_MODE": "ci-only", "CLEW_CI_TOKEN": "xxx"}
    mock_mod = _make_mock_ingest_module()
    with (
        patch.dict(os.environ, env),
        patch.dict(sys.modules, {"clewso_ingestion": MagicMock(), "clewso_ingestion.ingest": mock_mod}),
    ):
        result = runner.invoke(app, ["index", str(tmp_path)])

    assert result.exit_code == 0
    mock_mod.ingest_repo.assert_called_once()


def test_index_open_mode_allows_without_token(tmp_path):
    """open write mode (default) allows indexing without any token."""
    env = {"CLEW_WRITE_MODE": "open"}
    # Ensure CLEW_CI_TOKEN is unset
    mock_mod = _make_mock_ingest_module()
    with (
        patch.dict(os.environ, env),
        patch.dict(sys.modules, {"clewso_ingestion": MagicMock(), "clewso_ingestion.ingest": mock_mod}),
    ):
        os.environ.pop("CLEW_CI_TOKEN", None)
        result = runner.invoke(app, ["index", str(tmp_path)])

    assert result.exit_code == 0
    mock_mod.ingest_repo.assert_called_once()


# --- dry-run review tests ---


def test_review_dry_run_no_diff_exits_0():
    """--dry-run with no diff exits cleanly with code 0."""
    with patch("clew.cli.get_git_diff", return_value=""):
        result = runner.invoke(app, ["review", "--dry-run", "--pr"])
    assert result.exit_code == 0
    assert "No changes found" in result.output


def test_review_dry_run_json_output():
    """--dry-run --output json returns valid JSON."""
    diff = """diff --git a/src/foo.py b/src/foo.py
index 1234567..abcdefg 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
+import json
 def foo():
     pass
"""
    mock_dry_run_result = {
        "files_analyzed": 1,
        "impact_results": [
            {
                "path": "src/foo.py",
                "risk_level": "SAFE",
                "explanation": "No issues",
                "impact_count": 0,
                "affected_files": [],
                "recommendation": "None",
            }
        ],
        "violations": [],
        "has_blockers": False,
    }

    with (
        patch("clew.cli.get_git_diff", return_value=diff),
        patch("clew.cli.asyncio.run", return_value=mock_dry_run_result),
    ):
        result = runner.invoke(app, ["review", "--dry-run", "--output", "json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["files_analyzed"] == 1
    assert parsed["has_blockers"] is False


def test_review_dry_run_exit_1_on_blockers():
    """--dry-run exits 1 when blocking violations exist."""
    diff = """diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1 +1,2 @@
+import subprocess
"""
    mock_dry_run_result = {
        "files_analyzed": 1,
        "impact_results": [],
        "violations": [
            {
                "rule_id": "no-subprocess",
                "rule_type": "banned_import",
                "severity": "block",
                "message": "No subprocess",
                "file_path": "src/foo.py",
                "matched_pattern": "subprocess",
            }
        ],
        "has_blockers": True,
    }

    with (
        patch("clew.cli.get_git_diff", return_value=diff),
        patch("clew.cli.asyncio.run", return_value=mock_dry_run_result),
    ):
        result = runner.invoke(app, ["review", "--dry-run"])

    assert result.exit_code == 1
