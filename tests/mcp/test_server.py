import os
from unittest.mock import patch

import httpx
import pytest
import respx

# Import functions from the server module
# Import functions from the server module
from clew.mcp.server import explore_module, search_codebase, verify_concept


class TestMCPServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_search_codebase_success(self):
        """Test search_codebase tool success path."""
        # 1. Mock Search
        respx.post("http://localhost:8000/v1/search/").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "node1",
                        "score": 0.95,
                        "content": "def test(): pass",
                        "metadata": {"path": "test.py"},
                    }
                ],
            )
        )

        # 2. Mock Traverse (requested for top 3 results, only 1 here)
        respx.post("http://localhost:8000/v1/graph/traverse").mock(
            return_value=httpx.Response(
                200,
                json={
                    "nodes": [{"id": "test.py", "name": "test_func"}],
                    "edges": [{"source": "caller", "target": "test.py", "type": "CALLS"}],
                },
            )
        )

        with patch.dict(os.environ, {"CLEW_API_KEY": "test_key"}):
            result = await search_codebase("authentication")
            assert "test.py" in result
            assert "0.95" in result
            assert "Used By:" in result
            assert "caller -> CALLS" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_explore_module_success(self):
        """Test explore_module tool success path."""
        # 1. Mock Search to resolve path
        respx.post("http://localhost:8000/v1/search/").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "node1", "metadata": {"path": "src/app.py"}}],
            )
        )

        # 2. Mock Traverse (node IDs are paths, matching Neo4j output)
        respx.post("http://localhost:8000/v1/graph/traverse").mock(
            return_value=httpx.Response(
                200,
                json={
                    "nodes": [{"id": "src/app.py", "name": "app.py"}],
                    "edges": [{"source": "src/app.py", "target": "dep1", "type": "IMPORTS"}],
                },
            )
        )

        result = await explore_module("src/app.py")
        assert "graph" in result
        assert "IMPORTS" in result
        assert "DEPENDENCIES" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_explore_module_network_error(self):
        """Test explore_module tool with network error."""
        respx.post("http://localhost:8000/v1/search/").mock(side_effect=httpx.ConnectError("Connection refused"))

        result = await explore_module("src/app.py")
        assert "Network Error" in result
        assert "Could not connect" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_verify_concept_success(self):
        """Test verify_concept tool success path."""
        respx.post("http://localhost:8000/v1/search/").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "node1", "score": 0.98, "metadata": {"path": "auth.py"}}],
            )
        )

        result = await verify_concept("authentication")
        assert "SUCCESS" in result
        assert "auth.py" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_verify_concept_not_found(self):
        """Test verify_concept when no matches found."""
        respx.post("http://localhost:8000/v1/search/").mock(return_value=httpx.Response(200, json=[]))

        result = await verify_concept("nonexistent_concept")
        assert "FAILED" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_verify_concept_http_error(self):
        """Test verify_concept tool with HTTP error."""
        respx.post("http://localhost:8000/v1/search/").mock(
            return_value=httpx.Response(503, text="Service Unavailable")
        )

        result = await verify_concept("authentication")
        assert "API Error: 503" in result
