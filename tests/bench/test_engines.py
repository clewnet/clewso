"""Tests for context engine backends."""

import json

import httpx
import pytest

from bench.engines.base import ContextResult, estimate_tokens
from bench.engines.clew import ClewContextEngine
from bench.engines.standard_rag import StandardRAGEngine


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        assert estimate_tokens("hello world!") == 3  # 12 chars / 4

    def test_code_block(self):
        code = "def hello():\n    return 'world'\n"
        assert estimate_tokens(code) == len(code) // 4


class TestClewContextEngine:
    @pytest.fixture()
    def engine(self):
        return ClewContextEngine(api_url="http://test:8000", limit=5)

    @pytest.mark.asyncio()
    async def test_query_success(self, engine, respx_mock):
        respx_mock.post("http://test:8000/v1/search/").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": "1", "content": "def foo(): pass", "metadata": {"path": "src/foo.py"}, "score": 0.9},
                    {"id": "2", "content": "class Bar:", "metadata": {"path": "src/bar.py"}, "score": 0.8},
                ],
            )
        )

        result = await engine.query("find the foo function")

        assert isinstance(result, ContextResult)
        assert "src/foo.py" in result.context
        assert "src/bar.py" in result.context
        assert result.token_count > 0
        assert result.sources == ["src/foo.py", "src/bar.py"]

    @pytest.mark.asyncio()
    async def test_query_api_error(self, engine, respx_mock):
        respx_mock.post("http://test:8000/v1/search/").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await engine.query("anything")

        assert result.context == ""
        assert result.token_count == 0
        assert result.sources == []

    @pytest.mark.asyncio()
    async def test_query_sends_repo(self, respx_mock):
        engine = ClewContextEngine(api_url="http://test:8000", repo="my-repo")
        route = respx_mock.post("http://test:8000/v1/search/").mock(return_value=httpx.Response(200, json=[]))

        await engine.query("test")

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["repo"] == "my-repo"

    @pytest.mark.asyncio()
    async def test_close(self, engine):
        await engine.close()
        # Should not raise


class TestStandardRAGEngine:
    @pytest.fixture()
    def engine(self):
        return StandardRAGEngine(
            qdrant_url="http://qdrant:6333",
            embedding_url="http://embeddings:8080",
            limit=5,
        )

    @pytest.mark.asyncio()
    async def test_query_success(self, engine, respx_mock):
        # Mock embedding endpoint
        respx_mock.post("http://embeddings:8080/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": [0.1] * 1536}]},
            )
        )
        # Mock Qdrant query endpoint
        respx_mock.post("http://qdrant:6333/collections/codebase/points/query").mock(
            return_value=httpx.Response(
                200,
                json={
                    "result": {
                        "points": [
                            {"id": "1", "score": 0.95, "payload": {"path": "a.py", "text": "code a"}},
                            {"id": "2", "score": 0.85, "payload": {"path": "b.py", "text": "code b"}},
                        ]
                    }
                },
            )
        )

        result = await engine.query("find something")

        assert isinstance(result, ContextResult)
        assert "a.py" in result.context
        assert result.sources == ["a.py", "b.py"]

    @pytest.mark.asyncio()
    async def test_embedding_failure(self, engine, respx_mock):
        respx_mock.post("http://embeddings:8080/v1/embeddings").mock(return_value=httpx.Response(500, text="error"))

        result = await engine.query("test")

        assert result.context == ""
        assert result.token_count == 0

    @pytest.mark.asyncio()
    async def test_qdrant_failure(self, engine, respx_mock):
        respx_mock.post("http://embeddings:8080/v1/embeddings").mock(
            return_value=httpx.Response(200, json={"data": [{"embedding": [0.1] * 10}]})
        )
        respx_mock.post("http://qdrant:6333/collections/codebase/points/query").mock(
            return_value=httpx.Response(503, text="unavailable")
        )

        result = await engine.query("test")

        assert result.context == ""
