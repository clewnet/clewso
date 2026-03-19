"""Tests for the Coding LLM integration."""

import httpx
import pytest

from bench.coding_llm import CodingLLM


class TestCodingLLM:
    @pytest.fixture()
    def llm(self):
        return CodingLLM(api_key="sk-test-key", model="claude-test")

    @pytest.mark.asyncio()
    async def test_generate_success(self, llm, respx_mock):
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"text": "def foo():\n    pass"}],
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            )
        )

        code, usage = await llm.generate(
            instruction="write foo",
            success_criteria="foo exists",
            context="# context",
        )

        assert code == "def foo():\n    pass"
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    @pytest.mark.asyncio()
    async def test_generate_api_error(self, llm, respx_mock):
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(500, text="Overloaded")
        )

        code, usage = await llm.generate("task", "criteria", "ctx")

        assert "# Generation failed" in code
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    @pytest.mark.asyncio()
    async def test_close(self, llm):
        await llm.close()
