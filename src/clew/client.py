"""
Clew API Client

Provides a clean, reusable HTTP client for interacting with the Clew API.
Eliminates duplicated client setup and configuration logic.
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("clew.client")


class ClewAPIClient:
    """
    HTTP client for the Clew Context Engine API.

    Handles:
    - Configuration (base URL, headers, timeout)
    - Auth (API key for platform mode)
    - Connection management
    - Request execution with proper error handling

    Usage:
        async with ClewAPIClient() as client:
            results = await client.search("auth", limit=5)
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize the API client.

        Args:
            base_url: API base URL (default: from CONTEXT_ENGINE_API_URL env var)
            api_key: API key for authentication (default: from CLEW_API_KEY env var)
            timeout: Request timeout in seconds (default: from CLEW_API_TIMEOUT env var)
        """
        base_url = base_url or os.getenv("CLEW_API_URL", "http://localhost:8000/v1")
        if base_url is None:
            base_url = "http://localhost:8000/v1"
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key or os.getenv("CLEW_API_KEY")

        # Parse timeout from env
        try:
            self.timeout = float(os.getenv("CLEW_API_TIMEOUT", str(timeout)))
        except ValueError:
            logger.warning(f"Invalid CLEW_API_TIMEOUT value, defaulting to {timeout}")
            self.timeout = timeout

        # Build headers
        self.headers = {}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            logger.info("Platform mode enabled (API key present)")
        else:
            logger.info("Engine mode (localhost, no auth)")

        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        """Create HTTP client on context entry."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close HTTP client on context exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the underlying httpx client."""
        if not self._client:
            raise RuntimeError("ClewAPIClient must be used as async context manager")
        return self._client

    async def search(
        self,
        query: str,
        limit: int = 10,
        repo: str | None = None,
        filters: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for code using semantic similarity.

        Args:
            query: Natural language search query
            limit: Maximum number of results
            repo: Optional repository filter
            filters: Optional additional filters (path, type, etc.)

        Returns:
            List of search result dictionaries

        Raises:
            httpx.HTTPStatusError: If API returns error status
            httpx.RequestError: If network error occurs
        """
        search_data: dict[str, Any] = {"query": query, "limit": limit}
        if repo:
            search_data["repo"] = repo
        if filters:
            search_data["filters"] = filters

        logger.info(f"Searching: {search_data}")
        response = await self.client.post("search", json=search_data)
        response.raise_for_status()

        # Handle different response formats (list vs dict)
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get("results", [])

    async def traverse(
        self,
        start_node_id: str,
        relationship_types: list[str] | None = None,
        depth: int = 2,
    ) -> dict[str, Any]:
        """
        Traverse the code graph from a starting node.

        Args:
            start_node_id: ID of the node to start traversal from
            relationship_types: Types of relationships to follow (IMPORTS, CALLS, etc.)
            depth: How many hops to traverse

        Returns:
            Graph data with nodes and edges

        Raises:
            httpx.HTTPStatusError: If API returns error status
            httpx.RequestError: If network error occurs
        """
        traverse_data: dict[str, Any] = {"start_node_id": start_node_id, "depth": depth}
        if relationship_types:
            traverse_data["relationship_types"] = relationship_types

        logger.debug(f"Traversing from {start_node_id}")
        response = await self.client.post("graph/traverse", json=traverse_data)
        response.raise_for_status()

        return response.json()
