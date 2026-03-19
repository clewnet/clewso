from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable

from clew.server.adapters.neo4j import Neo4jStore


@pytest.fixture
def mock_driver():
    with patch("clew.server.adapters.neo4j.GraphDatabase.driver") as mock_driver_cls:
        driver_instance = MagicMock()
        mock_driver_cls.return_value = driver_instance
        yield driver_instance


@pytest.fixture
def store(mock_driver):
    return Neo4jStore(uri="bolt://localhost:7687", user="neo4j", password="password")


def test_lazy_initialization(store, mock_driver):
    assert store._driver is None
    driver = store.driver
    assert driver is mock_driver
    assert store._driver is not None


def test_close(store, mock_driver):
    _ = store.driver  # initialize
    store.close()
    mock_driver.close.assert_called_once()
    assert store._driver is None


@pytest.mark.asyncio
async def test_traverse_success(store, mock_driver):
    # Setup mock session and result
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    record1 = {
        "source_path": "file:src/main.py",
        "source_label": "File",
        "source_props": {"lines": 100},
        "target_path": "func:process",
        "target_label": "Function",
        "target_props": {},
        "rel_type": "DEFINES",
        "rel_id": "rel1",
        "rel_props": {},
    }

    record2 = {
        "source_path": "func:process",  # different source
        "source_label": "Function",
        "source_props": {},
        "target_path": "class:User",
        "target_label": "Class",
        "target_props": {},
        "rel_type": "CALLS",
        "rel_id": "rel2",
        "rel_props": {},
    }

    result_mock = [record1, record2]
    session_mock.run.return_value = result_mock

    result = await store.traverse("file:src/main.py")

    assert len(result.nodes) == 3  # main.py, process, User
    assert len(result.edges) == 2

    # Check nodes
    node_ids = {n.id for n in result.nodes}
    assert "file:src/main.py" in node_ids
    assert "func:process" in node_ids
    assert "class:User" in node_ids

    # Check edges
    edge_ids = {e.id for e in result.edges}
    assert "rel1" in edge_ids
    assert "rel2" in edge_ids


@pytest.mark.asyncio
async def test_traverse_filter_relationships(store, mock_driver):
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock
    session_mock.run.return_value = []

    await store.traverse("start_node", relationship_types=["IMPORTS", "INVALID_TYPE"])

    call_args = session_mock.run.call_args
    # Check that the query uses parameterized relationship types
    query = call_args[0][0]
    assert "$rel_types" in query

    # Check that only valid relationship types are passed in parameters
    # INVALID_TYPE should be filtered out
    params = call_args[1]
    assert params["rel_types"] == ["IMPORTS"]
    assert "INVALID_TYPE" not in params["rel_types"]

    # If I pass only invalid types, it should default to all allowed
    await store.traverse("start_node", relationship_types=["INVALID"])
    call_args = session_mock.run.call_args
    params = call_args[1]
    # Should contain all allowed types (passed as parameter, not in query string)
    allowed_types = {"IMPORTS", "CALLS", "CONTAINS", "DEFINES"}
    assert set(params["rel_types"]) == allowed_types


@pytest.mark.asyncio
async def test_traverse_handles_exception(store, mock_driver):
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock
    session_mock.run.side_effect = ServiceUnavailable("DB down")

    # Call traverse and expect it to raise (ERR-1 fix)
    with pytest.raises(ServiceUnavailable):
        await store.traverse("start_node")


@pytest.mark.asyncio
async def test_traverse_handles_missing_fields(store, mock_driver):
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    # Record with missing/None values which adapter handles with "unknown" or defaults
    record = {
        "source_path": None,
        "source_label": None,
        "source_props": None,
        "target_path": None,
        "target_label": None,
        "target_props": None,
        "rel_type": "TYPE",
        "rel_id": "rel1",
        "rel_props": None,
    }

    session_mock.run.return_value = [record]

    result = await store.traverse("start_node")

    assert len(result.nodes) == 1  # source and target are both "unknown", so deduped to 1
    node = result.nodes[0]
    assert node.id == "unknown"
    assert node.label == "Unknown"
    assert node.properties == {}

    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.source == "unknown"
    assert edge.target == "unknown"
    assert edge.properties == {}
