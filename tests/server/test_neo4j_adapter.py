from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable

from clew.server.adapters.neo4j import Neo4jStore


@pytest.fixture
def mock_driver():
    with patch("clew.server.adapters.neo4j.GraphDatabase.driver") as mock:
        driver_instance = MagicMock()
        mock.return_value = driver_instance
        yield driver_instance


@pytest.fixture
def store(mock_driver):
    return Neo4jStore("bolt://localhost:7687", "neo4j", "password")


@pytest.mark.asyncio
async def test_traverse_raises_generic_exception(store, mock_driver):
    # Setup the mock to raise a generic Exception
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock
    session_mock.run.side_effect = Exception("Generic error")

    # Call traverse and expect exception
    with pytest.raises(Exception) as excinfo:
        await store.traverse("some_id")

    assert "Generic error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_traverse_catches_neo4j_exception(store, mock_driver):
    # Setup the mock to raise a Neo4j exception
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock
    session_mock.run.side_effect = ServiceUnavailable("DB down")

    # Call traverse and expect it to raise (ERR-1 fix)
    with pytest.raises(ServiceUnavailable):
        await store.traverse("some_id")


@pytest.mark.asyncio
async def test_traverse_raises_bug_error(store, mock_driver):
    # Setup the mock to return data that causes a KeyError
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    # Return a record that misses 'source_path'
    record = {
        # "source_path": "path1",  <-- Missing
        "target_path": "path2",
        "source_label": "Label",
        "source_props": {},
        "target_label": "Label",
        "target_props": {},
        "rel_type": "TYPE",
        "rel_id": "1",
        "rel_props": {},
    }

    # Mock result object
    result_mock = MagicMock()
    result_mock.__iter__.return_value = [record]
    session_mock.run.return_value = result_mock

    # Call traverse and expect KeyError
    with pytest.raises(KeyError):
        await store.traverse("some_id")


@pytest.mark.asyncio
async def test_traverse_with_repo_id_includes_filter(store, mock_driver):
    """traverse() includes repo_id in the Cypher query when provided."""
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    # Return empty result set
    result_mock = MagicMock()
    result_mock.__iter__.return_value = iter([])
    session_mock.run.return_value = result_mock

    await store.traverse("src/main.py", repo_id="my-repo")

    # Verify session.run was called with repo_id in query and params
    call_args = session_mock.run.call_args
    query = call_args[0][0]
    assert "repo_id: $repo_id" in query, f"Expected repo_id filter in query: {query}"
    assert call_args[1]["repo_id"] == "my-repo"


@pytest.mark.asyncio
async def test_traverse_without_repo_id_omits_filter(store, mock_driver):
    """traverse() omits repo_id from the Cypher query when not provided."""
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    # Return empty result set
    result_mock = MagicMock()
    result_mock.__iter__.return_value = iter([])
    session_mock.run.return_value = result_mock

    await store.traverse("src/main.py")

    # Verify session.run was called without repo_id in query
    call_args = session_mock.run.call_args
    query = call_args[0][0]
    assert "repo_id: $repo_id" not in query, f"Unexpected repo_id filter in query: {query}"


@pytest.mark.asyncio
async def test_get_stats_with_repo_id(store, mock_driver):
    """get_stats scopes queries by repo_id when provided."""
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    # Two calls: node count then edge count
    node_record = MagicMock()
    node_record.__getitem__ = lambda self, k: 10 if k == "count" else None

    edge_record = MagicMock()
    edge_record.__getitem__ = lambda self, k: 5 if k == "count" else None

    node_result = MagicMock()
    node_result.single.return_value = node_record

    edge_result = MagicMock()
    edge_result.single.return_value = edge_record

    session_mock.run.side_effect = [node_result, edge_result]

    stats = await store.get_stats(repo_id="my-repo")

    assert stats["node_count"] == 10
    assert stats["edge_count"] == 5

    # Verify both queries included repo_id filtering
    calls = session_mock.run.call_args_list
    assert len(calls) == 2
    for call in calls:
        query = call[0][0]
        assert "repo_id" in query, f"Expected repo_id in query: {query}"
        assert call[1].get("repo_id") == "my-repo"


@pytest.mark.asyncio
async def test_get_stats_without_repo_id(store, mock_driver):
    """get_stats returns aggregate counts when repo_id is omitted."""
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    node_record = MagicMock()
    node_record.__getitem__ = lambda self, k: 20 if k == "count" else None

    edge_record = MagicMock()
    edge_record.__getitem__ = lambda self, k: 8 if k == "count" else None

    node_result = MagicMock()
    node_result.single.return_value = node_record

    edge_result = MagicMock()
    edge_result.single.return_value = edge_record

    session_mock.run.side_effect = [node_result, edge_result]

    stats = await store.get_stats()

    assert stats["node_count"] == 20
    assert stats["edge_count"] == 8

    # Verify queries do NOT include repo_id filtering
    calls = session_mock.run.call_args_list
    for call in calls:
        query = call[0][0]
        assert "repo_id" not in query, f"Unexpected repo_id in query: {query}"


# --- Policy CRUD ---


@pytest.mark.asyncio
async def test_create_policy(store, mock_driver):
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    record = MagicMock()
    record.__getitem__ = lambda self, k: "no-subprocess" if k == "id" else None
    result_mock = MagicMock()
    result_mock.single.return_value = record
    session_mock.run.return_value = result_mock

    policy = {
        "id": "no-subprocess",
        "type": "banned_import",
        "pattern": "subprocess",
        "severity": "block",
        "message": "Do not use subprocess",
        "precept_id": None,
    }
    result = await store.create_policy(policy)
    assert result == "no-subprocess"

    call_args = session_mock.run.call_args
    assert "MERGE (p:PolicyRule" in call_args[0][0]
    assert call_args[1]["id"] == "no-subprocess"


@pytest.mark.asyncio
async def test_get_policies(store, mock_driver):
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    records = [
        {
            "id": "no-subprocess",
            "type": "banned_import",
            "pattern": "subprocess",
            "severity": "block",
            "message": "No subprocess",
            "precept_id": None,
        },
    ]
    result_mock = MagicMock()
    result_mock.__iter__.return_value = iter(records)
    session_mock.run.return_value = result_mock

    policies = await store.get_policies()
    assert len(policies) == 1
    assert policies[0]["id"] == "no-subprocess"


@pytest.mark.asyncio
async def test_delete_policy(store, mock_driver):
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    record = MagicMock()
    record.__getitem__ = lambda self, k: 1 if k == "deleted" else None
    record.__bool__ = lambda self: True
    result_mock = MagicMock()
    result_mock.single.return_value = record
    session_mock.run.return_value = result_mock

    deleted = await store.delete_policy("no-subprocess")
    assert deleted is True
    assert session_mock.run.call_args[1]["id"] == "no-subprocess"


@pytest.mark.asyncio
async def test_delete_policy_not_found(store, mock_driver):
    session_mock = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = session_mock

    record = MagicMock()
    record.__getitem__ = lambda self, k: 0 if k == "deleted" else None
    record.__bool__ = lambda self: True
    result_mock = MagicMock()
    result_mock.single.return_value = record
    session_mock.run.return_value = result_mock

    deleted = await store.delete_policy("nonexistent")
    assert deleted is False
