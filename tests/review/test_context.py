import os
import sys
from unittest.mock import mock_open, patch

import pytest

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../src"))

from clew.review.context import ImpactedFile, fetch_review_context


@pytest.fixture
def impacted_files():
    return [
        ImpactedFile(path="src/a.py", node_id="1", incoming_edges=1, relationship="IMPORTS", score=10.0),
        ImpactedFile(path="src/b.py", node_id="2", incoming_edges=1, relationship="IMPORTS", score=5.0),
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
    impacts = [ImpactedFile(path="image.png", node_id="1", incoming_edges=1, relationship="IMPORTS")]

    ctx = fetch_review_context(impacts, "/repo")

    assert len(ctx.files) == 0


def test_fetch_context_token_limit(impacted_files):
    # content is 7 chars -> ~1 token
    # Max tokens = 1 -> should retrieve first file, then trunc second

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="content")),
    ):
        # Adjust estimate_tokens in context.py (len // 4)
        # "content" = 7 chars. 7//4 = 1 token.

        ctx = fetch_review_context(impacted_files, "/repo", max_tokens=1)

        # First file takes 1 token.
        # Second file: 1 + 1 > 1 -> skip

        assert len(ctx.files) == 1
        assert ctx.truncated
        assert ctx.truncated_count == 1


def test_fetch_context_path_traversal():
    impacts = [ImpactedFile(path="../secret.txt", node_id="1", incoming_edges=1, relationship="IMPORTS")]

    # Need to mock os.path.exists to true so it tries to check path
    # But os.path.abspath needs to work logically

    repo_root = "/repo"

    with patch("os.path.exists", return_value=True):
        ctx = fetch_review_context(impacts, repo_root)

    assert len(ctx.files) == 0  # Should be skipped by security check
