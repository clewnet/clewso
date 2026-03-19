import pytest

from clew.server.adapters.base import GraphNode, GraphResult


@pytest.mark.asyncio
async def test_get_file_pull_requests(client, mock_graph_store):
    """Test retrieving PRs for a file."""
    # Setup mock return value
    mock_graph_store.get_file_pull_requests.return_value = [
        GraphNode(id="pr:123", label="PullRequest", properties={"number": 123, "title": "Test PR"})
    ]

    response = await client.get("/v1/graph/file/src/main.py/pull_requests?repo_id=owner/repo")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["properties"]["number"] == 123

    mock_graph_store.get_file_pull_requests.assert_called_with("src/main.py", repo_id="owner/repo")


@pytest.mark.asyncio
async def test_get_pr_impact(client, mock_graph_store):
    """Test retrieving PR impact."""
    # Setup mock return value
    mock_graph_store.get_pr_impact.return_value = GraphResult(
        nodes=[GraphNode(id="file:1", label="File", properties={"path": "src/main.py"})], edges=[]
    )

    response = await client.get("/v1/graph/pull_request/123/impact?repo_id=owner/repo")

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["properties"]["path"] == "src/main.py"

    mock_graph_store.get_pr_impact.assert_called_with(123, "owner/repo")
