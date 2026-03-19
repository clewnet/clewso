import os
import sys
from unittest.mock import AsyncMock

import pytest

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../src"))

from clew.client import ClewAPIClient
from clew.review.graph import get_impact_radius


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=ClewAPIClient)
    return client


@pytest.mark.asyncio
async def test_get_impact_radius_found(mock_client):
    # Mock search response
    mock_client.search.return_value = [{"id": "node1", "metadata": {"path": "src/utils.py"}}]

    # Mock traverse response
    mock_client.traverse.return_value = {
        "nodes": [
            {"id": "node1", "metadata": {"path": "src/utils.py"}},
            {"id": "node2", "metadata": {"path": "src/main.py"}},
        ],
        "edges": [{"source": "node2", "target": "node1", "type": "IMPORTS"}],
    }

    impacts = await get_impact_radius(mock_client, "src/utils.py")

    assert len(impacts) == 1
    assert impacts[0].path == "src/main.py"
    assert impacts[0].relationship == "IMPORTS"
    # Score should be base 1.0 + 5.0 (main is critical) = 6.0
    assert impacts[0].score == 6.0


@pytest.mark.asyncio
async def test_get_impact_radius_not_found(mock_client):
    mock_client.search.return_value = []

    impacts = await get_impact_radius(mock_client, "new_file.py")

    assert len(impacts) == 0


@pytest.mark.asyncio
async def test_get_impact_radius_truncation(mock_client):
    mock_client.search.return_value = [{"id": "target", "metadata": {"path": "target.py"}}]

    # Create 15 consumers
    nodes = [{"id": "target", "metadata": {"path": "target.py"}}]
    edges = []
    for i in range(15):
        nodes.append({"id": f"node{i}", "metadata": {"path": f"consumer{i}.py"}})
        edges.append({"source": f"node{i}", "target": "target", "type": "IMPORTS"})

    mock_client.traverse.return_value = {"nodes": nodes, "edges": edges}

    impacts = await get_impact_radius(mock_client, "target.py", limit=10)

    assert len(impacts) == 10  # Should be truncated
