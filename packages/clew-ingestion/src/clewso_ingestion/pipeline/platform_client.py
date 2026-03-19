import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class PlatformClient:
    """Client for interacting with the Clew Platform API."""

    def __init__(self, platform_url: str, api_key: str):
        self.base_url = platform_url.rstrip("/")
        self.api_key = api_key
        # Use a single client for connection pooling
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-Clew-License-Key": self.api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self):
        await self.client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def send_signatures(
        self, repo_id: str, commit_hash: str, exports: list[dict[str, Any]], imports: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Send extracted signatures to the platform.

        Args:
            repo_id: The ID of the repository.
            commit_hash: The current commit hash.
            exports: List of exported symbols.
            imports: List of imported symbols.

        Returns:
            The platform response containing link results.

        Raises:
            httpx.HTTPStatusError: If the platform returns 4xx/5xx.
            httpx.NetworkError: If connection fails after retries.
        """
        payload = {"repo_id": repo_id, "commit_hash": commit_hash, "exports": exports, "imports": imports}

        logger.info(f"Sending {len(exports)} exports and {len(imports)} imports to platform for repo {repo_id}")

        response = await self.client.post("/v1/fleet/signatures", json=payload)
        response.raise_for_status()

        return response.json()
