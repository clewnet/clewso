import httpx
import pytest
import respx
from clewso_ingestion.pipeline.platform_client import PlatformClient


@pytest.fixture
def client():
    return PlatformClient(platform_url="http://test-platform.com", api_key="test-key")


@pytest.mark.asyncio
async def test_send_signatures_success(client):
    async with respx.mock(base_url="http://test-platform.com") as mock:
        mock.post("/v1/fleet/signatures").respond(200, json={"status": "success", "links_found": 5})

        repo_id = "test-repo"
        commit_hash = "abc1234"
        exports = [{"file_path": "a.py", "symbol_name": "A"}]
        imports = [{"file_path": "b.py", "symbol_name": "B"}]

        response = await client.send_signatures(repo_id, commit_hash, exports, imports)

        assert response["status"] == "success"
        assert response["links_found"] == 5

        request = mock.calls.last.request
        assert request.headers["X-Clew-License-Key"] == "test-key"
        import json

        payload = json.loads(request.content)
        assert payload["repo_id"] == repo_id
        assert payload["commit_hash"] == commit_hash
        assert payload["exports"] == exports
        assert payload["imports"] == imports

    await client.close()


@pytest.mark.asyncio
async def test_send_signatures_retry_on_network_error(client):
    async with respx.mock(base_url="http://test-platform.com") as mock:
        # Fail twice, succeed on third try
        route = mock.post("/v1/fleet/signatures")
        route.side_effect = [
            httpx.NetworkError("Connection failed"),
            httpx.NetworkError("Connection failed again"),
            httpx.Response(200, json={"status": "success"}),
        ]

        response = await client.send_signatures("repo", "commit", [], [])
        assert response["status"] == "success"
        assert mock.calls.call_count == 3

    await client.close()


@pytest.mark.asyncio
async def test_send_signatures_raises_http_status_error(client):
    async with respx.mock(base_url="http://test-platform.com") as mock:
        mock.post("/v1/fleet/signatures").respond(500)

        with pytest.raises(httpx.HTTPStatusError):
            await client.send_signatures("repo", "commit", [], [])

    await client.close()
