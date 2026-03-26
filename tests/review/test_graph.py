import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "../../src"))

from clew.review.graph import get_impact_radius


def _mock_session(query_results: dict[str, list[dict]]):
    """Create a mock Neo4j session that returns canned results per query pattern."""
    session = MagicMock()

    def run_side_effect(query, **kwargs):
        result = MagicMock()
        # Match query by checking which relationship type it queries
        for pattern, records in query_results.items():
            if pattern in query:
                result.__iter__ = lambda self, recs=records: iter(recs)
                return result
        result.__iter__ = lambda self: iter([])
        return result

    session.run = MagicMock(side_effect=run_side_effect)
    session.__enter__ = lambda self: session
    session.__exit__ = lambda self, *a: None
    return session


def _mock_driver(session):
    driver = MagicMock()
    driver.session.return_value = session
    return driver


@pytest.mark.asyncio
async def test_get_impact_radius_found():
    session = _mock_session(
        {
            "STARTS WITH": [{"path": "src/main.py"}],
            "DEFINES": [],
            "ENDS WITH": [],
        }
    )
    driver = _mock_driver(session)

    with patch("clew.review.graph._get_graph_backend", return_value=("neo4j", driver)):
        impacts = await get_impact_radius(None, "src/utils.py", repo_id="test/repo")

    assert len(impacts) == 1
    assert impacts[0].path == "src/main.py"
    assert impacts[0].relationship == "IMPORTS"
    assert impacts[0].score == 6.0  # 1.0 base + 5.0 (main is critical)


@pytest.mark.asyncio
async def test_get_impact_radius_not_found():
    session = _mock_session(
        {
            "STARTS WITH": [],
            "DEFINES": [],
            "ENDS WITH": [],
        }
    )
    driver = _mock_driver(session)

    with patch("clew.review.graph._get_graph_backend", return_value=("neo4j", driver)):
        impacts = await get_impact_radius(None, "new_file.py", repo_id="test/repo")

    assert len(impacts) == 0


@pytest.mark.asyncio
async def test_get_impact_radius_truncation():
    consumers = [{"path": f"consumer{i}.py"} for i in range(15)]
    session = _mock_session(
        {
            "STARTS WITH": consumers,
            "DEFINES": [],
            "ENDS WITH": [],
        }
    )
    driver = _mock_driver(session)

    with patch("clew.review.graph._get_graph_backend", return_value=("neo4j", driver)):
        impacts = await get_impact_radius(None, "target.py", limit=10, repo_id="test/repo")

    assert len(impacts) == 10


@pytest.mark.asyncio
async def test_get_impact_radius_ladybug_backend():
    """Test that the LadybugDB backend path is selected and queries run."""
    from clew.server.adapters.ladybug import LadybugUnifiedStore

    store = LadybugUnifiedStore(":memory:", embedding_dimension=4)
    store.create_repo_node("test/repo", "Test", "")
    store.create_file_node("test/repo", "src/utils.py", "q1")
    store.create_file_node("test/repo", "src/main.py", "q2")
    store.create_code_node("test/repo", "src/utils.py", "helper", "function", 1, 5, "q3")
    store.create_import_relationship("test/repo", "src/main.py", "utils")

    with patch("clew.review.graph._get_graph_backend", return_value=("ladybug", store)):
        impacts = await get_impact_radius(None, "src/utils.py", repo_id="test/repo")

    # src/main.py imports a module whose name starts with "utils" (the stem of utils.py)
    assert any(i.path == "src/main.py" for i in impacts)
