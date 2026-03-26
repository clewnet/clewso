import os
import sys
from unittest.mock import mock_open, patch

import pytest

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../src"))

from clew.review.context import fetch_review_context
from clew.review.graph import ImpactedFile


@pytest.fixture
def impacted_files():
    return [
        ImpactedFile(path="src/a.py", relationship="IMPORTS", score=10.0),
        ImpactedFile(path="src/b.py", relationship="IMPORTS", score=5.0),
    ]


def test_fetch_context_success(impacted_files):
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="content")),
    ):
        ctx = fetch_review_context(impacted_files, "/repo")

        assert len(ctx.files) == 2
        assert ctx.total_tokens > 0
        assert not ctx.truncated


def test_fetch_context_binary_skip():
    impacts = [ImpactedFile(path="image.png", relationship="IMPORTS")]

    ctx = fetch_review_context(impacts, "/repo")

    assert len(ctx.files) == 0


def test_fetch_context_token_limit(impacted_files):
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="content")),
    ):
        ctx = fetch_review_context(impacted_files, "/repo", max_tokens=1)

        assert len(ctx.files) == 1
        assert ctx.truncated
        assert ctx.truncated_count == 1


def test_fetch_context_path_traversal():
    impacts = [ImpactedFile(path="../secret.txt", relationship="IMPORTS")]

    repo_root = "/repo"

    with patch("os.path.exists", return_value=True):
        ctx = fetch_review_context(impacts, repo_root)

    assert len(ctx.files) == 0  # Should be skipped by security check
