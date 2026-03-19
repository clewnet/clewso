"""
Error Handling for MCP Tools

Provides a decorator pattern for consistent error handling across all tools.
Eliminates duplicated try/except blocks.
"""

import functools
import logging
from collections.abc import Callable

import httpx

logger = logging.getLogger("clew-mcp.errors")


def handle_api_errors(tool_func: Callable) -> Callable:
    """
    Decorator that wraps MCP tool functions with consistent error handling.

    This decorator catches common API errors and converts them to user-friendly
    error messages, eliminating the need for duplicated try/except blocks.

    Handles:
    - httpx.HTTPStatusError: API returned error status code
    - httpx.RequestError: Network/connection errors
    - Exception: Unexpected errors

    Usage:
        @mcp.tool()
        @handle_api_errors
        async def my_tool(query: str) -> str:
            # Tool logic here
            # No need for try/except!
            ...

    Args:
        tool_func: The async tool function to wrap

    Returns:
        Wrapped function with error handling
    """

    @functools.wraps(tool_func)
    async def wrapper(*args, **kwargs) -> str:
        tool_name = tool_func.__name__

        try:
            # Execute the tool function
            return await tool_func(*args, **kwargs)

        except httpx.HTTPStatusError as e:
            # API returned an error status code
            status = e.response.status_code
            detail = e.response.text

            logger.error(
                f"HTTP error in {tool_name}: {status} - {detail}",
                exc_info=True,
                extra={"tool": tool_name, "status_code": status},
            )

            return f"API Error: {status} - {detail}"

        except httpx.RequestError as e:
            # Network/connection error
            logger.error(
                f"Network error in {tool_name}: {e}",
                exc_info=True,
                extra={"tool": tool_name, "error_type": type(e).__name__},
            )

            return "Network Error: Could not connect to context engine. Check if the API is running."

        except Exception as e:
            # Unexpected error
            logger.error(
                f"Unexpected error in {tool_name}: {e}",
                exc_info=True,
                extra={"tool": tool_name, "error_type": type(e).__name__},
            )

            return f"Error executing {tool_name}: {str(e)}"

    return wrapper
