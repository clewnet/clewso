"""
Integration tests for Smart Reviewer pipeline (analyze_change_smart).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clew.cli import analyze_change_smart
from clew.review.context import FileContext, ReviewContext
from clew.review.llm import ReviewResult


@pytest.mark.asyncio
async def test_analyze_change_smart_flow(mocker):
    """Verify full pipeline: Impact -> Context -> Analysis."""
    mock_client = AsyncMock()
    repo_root = "/tmp/repo"
    file_path = "src/foo.py"
    diff = "diff content"

    # Mock Stage 1: Impact
    # We mock get_impact_radius at the module level because it's imported in cli.py
    with patch("clew.cli.get_impact_radius", new_callable=AsyncMock) as mock_impact:
        mock_impact.return_value = {"src/bar.py": MagicMock(path="src/bar.py")}

        # Mock Stage 2: Context
        with patch("clew.cli.fetch_review_context") as mock_context:
            mock_context.return_value = ReviewContext(
                files=[FileContext(path="src/bar.py", content="import foo", token_est=10, score=1.0)],
                total_tokens=10,
                truncated=False,
                truncated_count=0,
            )

            # Mock Stage 3: LLM
            with patch("clew.cli.analyze_impact", new_callable=AsyncMock) as mock_analyze:
                mock_analyze.return_value = ReviewResult(
                    risk_level="HIGH",
                    explanation="Breaking change",
                    affected_files=["src/bar.py"],
                    recommendation="Revert",
                )

                result = await analyze_change_smart(mock_client, file_path, diff, repo_root)

                assert result["path"] == "src/foo.py"
                assert result["risk_level"] == "HIGH"
                assert result["impact_count"] == 1
                assert result["affected_files"] == ["src/bar.py"]

                # Check call chain
                mock_impact.assert_called_once()
                mock_context.assert_called_once()
                mock_analyze.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_change_smart_handles_errors(mocker):
    """Verify error handling in pipeline."""
    mock_client = AsyncMock()

    # Force error in Stage 1
    with patch("clew.cli.get_impact_radius", side_effect=Exception("API Down")):
        result = await analyze_change_smart(mock_client, "src/foo.py", "diff", "/tmp")

        assert result["risk_level"] == "UNKNOWN"
        assert "API Down" in result["explanation"]
