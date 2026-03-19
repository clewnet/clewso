"""
Tests for error handling decorator.

Verifies that the @handle_api_errors decorator properly catches
and formats different error types.
"""

import httpx
import pytest

from clew.mcp.errors import handle_api_errors


@handle_api_errors
async def mock_tool_success():
    """Mock tool that succeeds."""
    return "Success!"


@handle_api_errors
async def mock_tool_http_error():
    """Mock tool that raises HTTPStatusError."""
    response = httpx.Response(status_code=404, text="Not Found")
    raise httpx.HTTPStatusError("404 error", request=None, response=response)


@handle_api_errors
async def mock_tool_network_error():
    """Mock tool that raises RequestError."""
    raise httpx.RequestError("Connection refused")


@handle_api_errors
async def mock_tool_unexpected_error():
    """Mock tool that raises unexpected error."""
    raise ValueError("Something went wrong")


@pytest.mark.asyncio
async def test_decorator_success():
    """Test that decorator doesn't interfere with successful execution."""
    result = await mock_tool_success()
    assert result == "Success!"


@pytest.mark.asyncio
async def test_decorator_http_error():
    """Test that HTTPStatusError is caught and formatted."""
    result = await mock_tool_http_error()
    assert "API Error" in result
    assert "404" in result
    assert "Not Found" in result


@pytest.mark.asyncio
async def test_decorator_network_error():
    """Test that RequestError is caught and formatted."""
    result = await mock_tool_network_error()
    assert "Network Error" in result
    assert "Could not connect" in result


@pytest.mark.asyncio
async def test_decorator_unexpected_error():
    """Test that unexpected exceptions are caught and formatted."""
    result = await mock_tool_unexpected_error()
    assert "Error executing" in result
    assert "Something went wrong" in result


@pytest.mark.asyncio
async def test_decorator_preserves_function_metadata():
    """Test that decorator preserves function name and docstring."""

    @handle_api_errors
    async def my_custom_tool(arg1: str) -> str:
        """This is my custom tool."""
        return f"Result: {arg1}"

    assert my_custom_tool.__name__ == "my_custom_tool"
    assert "custom tool" in my_custom_tool.__doc__
