"""Tests for Judge LLM integration."""

import json

import httpx
import pytest

from bench.judge import JudgeLLM, _parse_judgement_json
from bench.models import Judgement

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"


def _gemini_response(text: str) -> httpx.Response:
    """Build a mock Gemini API response containing the given text."""
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
    )


class TestParseJudgementJson:
    def test_plain_json(self):
        text = json.dumps({"correctness": 4, "efficiency": 5, "hallucinations": [], "comments": "good"})
        result = _parse_judgement_json(text)
        assert result["correctness"] == 4
        assert result["efficiency"] == 5

    def test_json_with_markdown_fences(self):
        inner = json.dumps({"correctness": 3, "efficiency": 4, "hallucinations": ["foo"], "comments": "ok"})
        text = f"```json\n{inner}\n```"
        result = _parse_judgement_json(text)
        assert result["correctness"] == 3
        assert result["hallucinations"] == ["foo"]

    def test_json_with_surrounding_text(self):
        inner = json.dumps({"correctness": 5, "efficiency": 5, "hallucinations": [], "comments": "perfect"})
        text = f"Here is my evaluation:\n{inner}\nThat is all."
        result = _parse_judgement_json(text)
        assert result["correctness"] == 5

    def test_invalid_json_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_judgement_json("not json at all")


class TestJudgeLLM:
    @pytest.fixture()
    def judge(self):
        return JudgeLLM(api_key="test-key", model="gemini-test")

    @pytest.mark.asyncio()
    async def test_evaluate_success(self, judge, respx_mock):
        text = json.dumps({"correctness": 5, "efficiency": 4, "hallucinations": [], "comments": "Well done"})
        respx_mock.post(GEMINI_URL).mock(return_value=_gemini_response(text))

        result = await judge.evaluate("Create a user model", "Model exists", "class User: pass")

        assert isinstance(result, Judgement)
        assert result.correctness == 5
        assert result.efficiency == 4
        assert result.hallucinations == []
        assert result.comments == "Well done"

    @pytest.mark.asyncio()
    async def test_evaluate_with_hallucinations(self, judge, respx_mock):
        text = json.dumps(
            {
                "correctness": 2,
                "efficiency": 3,
                "hallucinations": ["import nonexistent_module", "call_fake_function()"],
                "comments": "Uses non-existent imports",
            }
        )
        respx_mock.post(GEMINI_URL).mock(return_value=_gemini_response(text))

        result = await judge.evaluate("Do task", "It works", "import nonexistent_module")

        assert result.correctness == 2
        assert len(result.hallucinations) == 2

    @pytest.mark.asyncio()
    async def test_evaluate_api_failure_returns_neutral(self, judge, respx_mock):
        respx_mock.post(GEMINI_URL).mock(return_value=httpx.Response(500, text="Internal Error"))

        result = await judge.evaluate("task", "criteria", "code")

        # Should return neutral scores, not raise
        assert result.correctness == 3
        assert result.efficiency == 3
        assert "failed" in result.comments.lower()

    @pytest.mark.asyncio()
    async def test_evaluate_clamps_scores(self, judge, respx_mock):
        text = json.dumps({"correctness": 99, "efficiency": -1, "hallucinations": [], "comments": "weird"})
        respx_mock.post(GEMINI_URL).mock(return_value=_gemini_response(text))

        result = await judge.evaluate("task", "criteria", "code")

        assert result.correctness == 5  # clamped to max
        assert result.efficiency == 1  # clamped to min
