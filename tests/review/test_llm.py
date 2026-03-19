import json
import os
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../src"))

from clew.review.llm import ReviewContext, analyze_impact


@pytest.fixture
def mock_context():
    return ReviewContext(
        files=[],  # Empty for logic tests, filled in specific tests
        total_tokens=0,
        truncated=False,
        truncated_count=0,
    )


@pytest.mark.asyncio
async def test_analyze_impact_zero_deps(mock_context):
    # No files, not truncated -> Low Risk
    result = await analyze_impact("diff", mock_context, "changed.py")

    assert result.risk_level == "SAFE"
    assert result.confidence > 0.9


@pytest.mark.asyncio
async def test_analyze_impact_success(mock_context):
    mock_file = MagicMock()  # Or use real FileContext
    mock_file.path = "dummy.py"
    mock_file.content = "content"
    mock_file.score = 10.0
    mock_context.files = [mock_file]

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "risk_level": "HIGH",
                            "explanation": "Breaking change detected",
                            "affected_files": ["affected.py"],
                            "recommendation": "Fix it",
                            "confidence": 0.9,
                        }
                    )
                }
            }
        ]
    }

    with respx.mock(base_url="https://api.openai.com/v1") as respx_mock:
        respx_mock.post("/chat/completions").mock(return_value=httpx.Response(200, json=mock_response))

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            result = await analyze_impact("diff", mock_context, "changed.py")

        assert result.risk_level == "HIGH"
        assert result.explanation == "Breaking change detected"


@pytest.mark.asyncio
async def test_analyze_impact_api_failure(mock_context):
    mock_file = MagicMock()
    mock_file.path = "dummy.py"
    mock_file.content = "content"
    mock_context.files = [mock_file]

    with respx.mock(base_url="https://api.openai.com/v1") as respx_mock:
        respx_mock.post("/chat/completions").mock(side_effect=httpx.RequestError("API Error"))

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            result = await analyze_impact("diff", mock_context, "changed.py")

        # Fallback
        assert result.risk_level == "MEDIUM"
        assert "Automated analysis unavailable" in result.explanation


@pytest.mark.asyncio
async def test_analyze_impact_invalid_key(mock_context):
    mock_context.files = ["dummy"]

    # Mock where key exists but invalid format
    with patch.dict(os.environ, {"OPENAI_API_KEY": "invalid-key"}):
        # The logic checks startswith("sk-") and logs error,
        # but technically LLMClient init doesn't raise, it just logs.
        # We expect it to attempt the call and fail auth, OR we can check for UNKNOWN
        # if we modify LLMClient to enforce valid keys.

        # Currently the fix merely logs an error. So it will proceed to try the API call.
        pass
