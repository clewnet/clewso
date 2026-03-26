"""Tests for LadybugUnifiedStore using in-memory LadybugDB."""

import pytest

from clew.server.adapters.ladybug import LadybugUnifiedStore, _instances


@pytest.fixture(autouse=True)
def _clear_instance_cache():
    """Clear the shared instance cache between tests."""
    _instances.clear()
    yield
    _instances.clear()


@pytest.fixture
def store():
    """Create an in-memory LadybugDB store for testing."""
    return LadybugUnifiedStore(":memory:", embedding_dimension=4)


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------


def test_ensure_schema_creates_tables(store):
    """Schema should create all node and relationship tables."""
    rows = store._conn.execute("CALL show_tables() RETURN *").get_all()
    table_names = {r[1] for r in rows}  # name is at index 1
    assert "File" in table_names
    assert "Module" in table_names
    assert "Function" in table_names
    assert "CodeBlock" in table_names
    assert "Repository" in table_names
    assert "PullRequest" in table_names
    assert "PolicyRule" in table_names
    assert "File_IMPORTS_Module" in table_names
    assert "Repository_CONTAINS_File" in table_names


def test_ensure_schema_stores_dimension(store):
    rows = store._conn.execute("MATCH (m:_metadata {key: 'embedding_dimension'}) RETURN m.value").get_all()
    assert rows[0][0] == "4"


def test_dimension_mismatch_raises(store):
    # Re-running ensure_schema with a different dimension should fail
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        store._dimension = 8
        store.ensure_schema()


# ------------------------------------------------------------------
# GraphWriter — repo, file, code nodes
# ------------------------------------------------------------------


def test_create_repo_node(store):
    store.create_repo_node("test-repo", "Test Repo", "https://example.com")
    rows = store._conn.execute("MATCH (r:Repository {id: 'test-repo'}) RETURN r.name").get_all()
    assert rows[0][0] == "Test Repo"


def test_create_file_node(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/main.py", "q1")
    rows = store._conn.execute("MATCH (f:File {repo_id: 'r1'}) RETURN f.path").get_all()
    assert rows[0][0] == "src/main.py"


def test_create_code_node(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/main.py", "q1")
    store.create_code_node("r1", "src/main.py", "my_func", "function", 10, 20, "q2")
    rows = store._conn.execute("MATCH (c:CodeBlock {name: 'my_func'}) RETURN c.start_line, c.end_line").get_all()
    assert rows[0] == [10, 20]


def test_create_import_relationship(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/main.py", "q1")
    store.create_import_relationship("r1", "src/main.py", "os")
    rows = store._conn.execute("MATCH (:File)-[:File_IMPORTS_Module]->(m:Module) RETURN m.name").get_all()
    assert rows[0][0] == "os"


def test_create_call_relationship(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/main.py", "q1")
    store.create_call_relationship("r1", "src/main.py", "print")
    rows = store._conn.execute("MATCH (:File)-[:File_CALLS_Function]->(fn:Function) RETURN fn.name").get_all()
    assert rows[0][0] == "print"


# ------------------------------------------------------------------
# GraphWriter — delete, commit tracking
# ------------------------------------------------------------------


def test_delete_file_node(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/main.py", "q1")
    count = store.delete_file_node("r1", "src/main.py")
    assert count == 1
    rows = store._conn.execute("MATCH (f:File {repo_id: 'r1'}) RETURN count(f)").get_all()
    assert rows[0][0] == 0


def test_last_indexed_commit(store):
    store.create_repo_node("r1", "Repo", "")
    assert store.get_last_indexed_commit("r1") is None
    store.update_last_indexed_commit("r1", "abc123")
    assert store.get_last_indexed_commit("r1") == "abc123"


# ------------------------------------------------------------------
# GraphStore — traverse, stats, neighbors
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traverse_returns_edges(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/main.py", "q1")
    store.create_import_relationship("r1", "src/main.py", "os")

    result = await store.traverse("src/main.py")
    assert len(result.nodes) >= 2
    assert any(e.type == "IMPORTS" for e in result.edges)


@pytest.mark.asyncio
async def test_get_stats(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/main.py", "q1")
    stats = await store.get_stats()
    assert stats["node_count"] >= 1


@pytest.mark.asyncio
async def test_get_neighbors_batch(store):
    store.create_repo_node("r1", "Repo", "")
    store.create_file_node("r1", "src/a.py", "q1")
    store.create_file_node("r1", "src/b.py", "q2")
    store.create_import_relationship("r1", "src/a.py", "shared_mod")
    store.create_import_relationship("r1", "src/b.py", "shared_mod")

    neighbors = await store.get_neighbors_batch(["src/a.py"])
    assert "src/b.py" in neighbors.get("src/a.py", [])


# ------------------------------------------------------------------
# Policy CRUD
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_crud(store):
    pid = await store.create_policy(
        {"id": "p1", "type": "banned_import", "pattern": "os.system", "severity": "block", "message": "no shell"}
    )
    assert pid == "p1"

    policies = await store.get_policies()
    assert len(policies) == 1
    assert policies[0]["pattern"] == "os.system"

    deleted = await store.delete_policy("p1")
    assert deleted is True
    assert len(await store.get_policies()) == 0


# ------------------------------------------------------------------
# Shared instance
# ------------------------------------------------------------------


def test_get_or_create_returns_same_instance(tmp_path):
    path = str(tmp_path / "test_db")
    a = LadybugUnifiedStore.get_or_create(path, 4)
    b = LadybugUnifiedStore.get_or_create(path, 4)
    assert a is b
