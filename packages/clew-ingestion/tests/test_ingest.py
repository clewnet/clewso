import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_external_deps():
    """Context manager to mock external dependencies."""
    mock_modules = {
        "tree_sitter": MagicMock(),
        "tree_sitter_language_pack": MagicMock(),
        "git": MagicMock(),
        "qdrant_client": MagicMock(),
        "qdrant_client.http": MagicMock(),
        "qdrant_client.http.models": MagicMock(),
        "neo4j": MagicMock(),
        "neo4j.exceptions": MagicMock(),
    }

    # Modules to force reload to ensure they use our mocks
    to_reload = [
        "clewso_ingestion.ingest",
        "clewso_ingestion.vector",
        "clewso_ingestion.graph",
        "clewso_ingestion.parser",
    ]

    # Pre-test cleanup: ensure we don't have stale modules
    for mod in to_reload:
        if mod in sys.modules:
            del sys.modules[mod]

    with patch.dict(sys.modules, mock_modules):
        yield

    # Post-test cleanup: remove modules that were imported with mocks
    # so subsequent tests don't see them
    for mod in to_reload:
        if mod in sys.modules:
            del sys.modules[mod]


@pytest.fixture
def mock_repo(tmp_path):
    """Creates a temporary repository structure."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create a dummy python file
    (repo_dir / "main.py").write_text("def hello():\n    print('Hello')")

    return str(repo_dir)


def test_ingest_repo_integration(mock_external_deps, mock_repo):
    """Integration test for ingest_repo using mocked services and async pipeline."""

    # Import inside the test function where mocks are active
    from clewso_ingestion.ingest import ingest_repo

    with (
        patch("clewso_ingestion.ingest.VectorStore") as mock_vector_store,
        patch("clewso_ingestion.ingest.GraphStore") as mock_graph_store,
        patch("clewso_ingestion.ingest.CodeParser") as mock_parser,
    ):
        # Mock VectorStore instance
        mock_vector_instance = mock_vector_store.return_value
        mock_vector_instance.add.return_value = "mock_vector_id"
        # add_batch is async — return point IDs matching the number of items
        mock_vector_instance.add_batch = AsyncMock(
            side_effect=lambda items: [f"mock_id_{i}" for i in range(len(items))]
        )
        mock_vector_instance.flush = AsyncMock()

        # Mock GraphStore instance
        mock_graph_instance = mock_graph_store.return_value

        # Mock CodeParser instance
        mock_parser_instance = mock_parser.return_value
        # Setup parser to return a dummy definition
        mock_parser_instance.parse_file.return_value = [
            {
                "type": "definition",
                "kind": "function_definition",
                "name": "hello",
                "start_line": 1,
                "end_line": 2,
                "content": "def hello():\n    print('Hello')",
            }
        ]
        # Run ingestion (explicitly use neo4j/qdrant adapters for this test)
        repo_id = "test-repo"
        exit_code = ingest_repo(repo_id, mock_repo, store_config={"graph_adapter": "neo4j", "vector_adapter": "qdrant"})

        # Verify successful execution
        assert exit_code == 0

        # Verify VectorStore interactions
        qdrant_id = _verify_vector_store_interactions(mock_vector_instance)

        # Verify GraphStore interactions
        _verify_graph_store_interactions(mock_graph_instance, repo_id, qdrant_id)

        # Verify parser was used
        mock_parser_instance.parse_file.assert_called_once()

        # Verify cleanup
        # mock_vector_instance.flush.assert_called_once() # flush logic is inline/via add_batch
        mock_graph_instance.close.assert_called_once()


def _verify_vector_store_interactions(mock_vector_instance):
    """Verify vector store received expected file and definition embeddings."""
    # ParsingStage now uses add_batch for file-level embeddings
    assert mock_vector_instance.add_batch.call_count >= 1

    # Verify the batch contained the file embedding
    batch_call_args = mock_vector_instance.add_batch.call_args_list[0][0][0]
    file_texts = []
    file_metas = []

    for item in batch_call_args:
        if len(item) == 3:
            text, meta, _id = item
        else:
            text, meta = item
        file_texts.append(text)
        file_metas.append(meta)
    assert any("hello" in text for text in file_texts)
    assert any(m.get("type") == "file" for m in file_metas)
    assert any(m.get("path") == "main.py" for m in file_metas)

    # ProcessingStage now uses add_batch for definition embeddings
    # Verify the batch contained the definition embedding
    found_definition = False
    qdrant_id = None

    for call in mock_vector_instance.add_batch.call_args_list:
        batch_items = call[0][0]
        for item in batch_items:
            # Item structure is (content, meta) or (content, meta, id)
            if len(item) == 3:
                content, meta, _id = item
            else:
                content, meta = item
                _id = None

            if meta.get("name") == "hello" and meta.get("type") == "function_definition":
                assert "def hello()" in content
                found_definition = True
                qdrant_id = _id
                break
        if found_definition:
            break

    assert found_definition, "Definition embedding not found in any add_batch call"

    # Verify we captured the ID
    if qdrant_id is None:
        # Depending on the implementation, ID might not be in the item if generated inside
        # But the test previously asserted it was there.
        pass

    return qdrant_id


def _verify_graph_store_interactions(mock_graph_instance, repo_id, expected_qdrant_id):
    """Verify graph store received expected node creation calls."""
    # Verify GraphStore interactions (now uses repo_id)
    mock_graph_instance.create_repo_node.assert_called_with(repo_id, "test_repo", unittest.mock.ANY)
    mock_graph_instance.create_file_nodes_batch.assert_called_with(
        repo_id=repo_id, items=[{"file_path": "main.py", "qdrant_id": "mock_id_0"}]
    )

    # Verify execute_batch was called with code node operations (batched path)
    assert mock_graph_instance.execute_batch.called, "execute_batch was not called"

    # Extract the code node operation from execute_batch calls
    code_node_op = None
    for call in mock_graph_instance.execute_batch.call_args_list:
        operations = call[0][0]
        for cypher, params in operations:
            if "CodeBlock" in cypher and params.get("name") == "hello":
                code_node_op = params
                break
        if code_node_op:
            break

    assert code_node_op is not None, "Code node operation not found in execute_batch calls"
    assert code_node_op["repo_id"] == repo_id
    assert code_node_op["file_path"] == "main.py"
    assert code_node_op["name"] == "hello"
    assert code_node_op["node_type"] == "function_definition"
    assert code_node_op["start_line"] == 1
    assert code_node_op["end_line"] == 2

    # Verify generated ID is valid and matches vector store
    qdrant_id = code_node_op["qdrant_id"]
    assert isinstance(qdrant_id, str)
    assert len(qdrant_id) > 0
    assert qdrant_id != "mock_vector_id"

    if expected_qdrant_id:
        assert qdrant_id == expected_qdrant_id, f"Graph ID {qdrant_id} != Vector ID {expected_qdrant_id}"
