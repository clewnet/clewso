import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock neo4j before importing src.graph
mock_neo4j = MagicMock()
sys.modules["neo4j"] = mock_neo4j

from clewso_ingestion.graph import GraphStore  # noqa: E402


class TestGraphStore(unittest.TestCase):
    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_init(self, mock_graph_database):
        # Setup environment variables
        with patch.dict(
            os.environ,
            {
                "NEO4J_URI": "bolt://test:7687",
                "NEO4J_USER": "testuser",
                "NEO4J_PASSWORD": "testpassword",
            },
        ):
            store = GraphStore()

            mock_graph_database.driver.assert_called_once_with("bolt://test:7687", auth=("testuser", "testpassword"))
            self.assertEqual(store.driver, mock_graph_database.driver.return_value)

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_close(self, mock_graph_database):
        store = GraphStore()
        store.close()
        store.driver.close.assert_called_once()

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_create_repo_node(self, mock_graph_database):
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        repo_id = "repo-123"
        repo_name = "test-repo"
        repo_url = "http://github.com/test/repo"

        store.create_repo_node(repo_id, repo_name, repo_url)

        mock_session.run.assert_called_once_with(
            "MERGE (r:Repository {id: $repo_id}) SET r.name = $name, r.url = $url",
            repo_id=repo_id,
            url=repo_url,
            name=repo_name,
        )

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_create_file_node(self, mock_graph_database):
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        repo_id = "repo-123"
        file_path = "src/main.py"
        qdrant_id = "uuid-123"

        store.create_file_node(repo_id, file_path, qdrant_id)

        args, kwargs = mock_session.run.call_args
        self.assertIn("MATCH (r:Repository {id: $repo_id})", args[0])
        self.assertIn("MERGE (f:File {path: $file_path, repo_id: $repo_id})", args[0])
        self.assertEqual(kwargs, {"repo_id": repo_id, "file_path": file_path, "qdrant_id": qdrant_id})

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_create_code_node(self, mock_graph_database):
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        repo_id = "repo-123"
        file_path = "src/main.py"
        name = "my_function"
        node_type = "function"
        start_line = 10
        end_line = 20
        qdrant_id = "uuid-456"

        store.create_code_node(repo_id, file_path, name, node_type, start_line, end_line, qdrant_id)

        args, kwargs = mock_session.run.call_args
        self.assertIn("MATCH (f:File {repo_id: $repo_id, path: $file_path})", args[0])
        self.assertIn("MERGE (c:CodeBlock {", args[0])
        self.assertEqual(
            kwargs,
            {
                "repo_id": repo_id,
                "file_path": file_path,
                "name": name,
                "node_type": node_type,
                "start_line": start_line,
                "end_line": end_line,
                "qdrant_id": qdrant_id,
            },
        )

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_create_import_relationship(self, mock_graph_database):
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        repo_id = "repo-123"
        file_path = "src/main.py"
        module_name = "os"

        store.create_import_relationship(repo_id, file_path, module_name)

        args, kwargs = mock_session.run.call_args
        self.assertIn("MATCH (f:File {repo_id: $repo_id, path: $file_path})", args[0])
        self.assertIn("MERGE (m:Module {name: $module_name, repo_id: $repo_id})", args[0])
        self.assertIn("MERGE (f)-[:IMPORTS]->(m)", args[0])
        self.assertEqual(kwargs, {"repo_id": repo_id, "file_path": file_path, "module_name": module_name})

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_create_call_relationship(self, mock_graph_database):
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        repo_id = "repo-123"
        file_path = "src/main.py"
        target_name = "other_function"

        store.create_call_relationship(repo_id, file_path, target_name)

        args, kwargs = mock_session.run.call_args
        self.assertIn("MATCH (f:File {repo_id: $repo_id, path: $file_path})", args[0])
        self.assertIn("MERGE (t:Function {name: $target_name, repo_id: $repo_id})", args[0])
        self.assertIn("MERGE (f)-[:CALLS]->(t)", args[0])
        self.assertEqual(kwargs, {"repo_id": repo_id, "file_path": file_path, "target_name": target_name})

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_execute_batch(self, mock_graph_database):
        """Test execute_batch runs multiple Cypher queries in a single transaction."""
        store = GraphStore()
        mock_session = MagicMock()
        mock_tx = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session
        mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

        operations = [
            ("MERGE (n:Node {id: $id})", {"id": "1"}),
            ("MERGE (n:Node {id: $id})", {"id": "2"}),
            ("MATCH (a {id: $a}), (b {id: $b}) MERGE (a)-[:REL]->(b)", {"a": "1", "b": "2"}),
        ]

        store.execute_batch(operations)

        # Verify a single transaction was used
        mock_session.begin_transaction.assert_called_once()

        # Verify all queries were run within the transaction
        self.assertEqual(mock_tx.run.call_count, 3)
        mock_tx.run.assert_any_call("MERGE (n:Node {id: $id})", id="1")
        mock_tx.run.assert_any_call("MERGE (n:Node {id: $id})", id="2")
        mock_tx.run.assert_any_call("MATCH (a {id: $a}), (b {id: $b}) MERGE (a)-[:REL]->(b)", a="1", b="2")

        # Verify transaction was committed
        mock_tx.commit.assert_called_once()

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_execute_batch_empty(self, mock_graph_database):
        """Test execute_batch with empty operations list is a no-op."""
        store = GraphStore()

        # Should not open a session at all
        store.driver.session.reset_mock()
        store.execute_batch([])
        store.driver.session.assert_not_called()

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_ensure_schema_creates_constraints(self, mock_graph_database):
        """Test that _ensure_schema is called on init and creates all constraints."""
        mock_session = MagicMock()
        mock_graph_database.driver.return_value.session.return_value.__enter__.return_value = mock_session

        # Create GraphStore (should call _ensure_schema in __init__)
        GraphStore()

        # Verify session.run was called multiple times for constraints and indexes
        self.assertGreaterEqual(mock_session.run.call_count, 6)  # 2 constraints + 4 indexes

        # Verify constraint creation queries
        calls = [call[0][0] for call in mock_session.run.call_args_list]

        # Check for file constraint
        self.assertTrue(
            any("file_repo_path_unique" in call for call in calls),
            "File constraint should be created",
        )

        # Check for codeblock constraint
        self.assertTrue(
            any("codeblock_unique" in call for call in calls),
            "CodeBlock constraint should be created",
        )

        # Check for indexes
        self.assertTrue(any("file_repo_id" in call for call in calls), "File repo_id index should be created")
        self.assertTrue(
            any("codeblock_repo_id" in call for call in calls),
            "CodeBlock repo_id index should be created",
        )

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_ensure_schema_idempotent(self, mock_graph_database):
        """Test that _ensure_schema uses IF NOT EXISTS for idempotency."""
        mock_session = MagicMock()
        mock_graph_database.driver.return_value.session.return_value.__enter__.return_value = mock_session

        # Create GraphStore
        GraphStore()

        # Verify all schema statements use IF NOT EXISTS
        calls = [call[0][0] for call in mock_session.run.call_args_list]

        for call in calls:
            if "CREATE CONSTRAINT" in call or "CREATE INDEX" in call:
                self.assertIn("IF NOT EXISTS", call, f"Schema statement should be idempotent: {call}")

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_ensure_schema_handles_errors(self, mock_graph_database):
        """Test that _ensure_schema raises exception on failure."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Neo4j connection failed")
        mock_graph_database.driver.return_value.session.return_value.__enter__.return_value = mock_session

        # Should raise exception when schema creation fails
        with self.assertRaises(Exception) as context:
            GraphStore()

        self.assertIn("Neo4j connection failed", str(context.exception))

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_get_last_indexed_commit_returns_sha(self, mock_graph_database):
        """Test get_last_indexed_commit returns SHA when repo has been indexed."""
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        mock_record = {"sha": "abc123def456"}
        mock_session.run.return_value.single.return_value = mock_record

        result = store.get_last_indexed_commit("repo-123")

        self.assertEqual(result, "abc123def456")
        mock_session.run.assert_called_once_with(
            "MATCH (r:Repository {id: $repo_id}) RETURN r.last_indexed_commit AS sha",
            repo_id="repo-123",
        )

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_get_last_indexed_commit_returns_none_when_not_found(self, mock_graph_database):
        """Test get_last_indexed_commit returns None when repo doesn't exist."""
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        mock_session.run.return_value.single.return_value = None

        result = store.get_last_indexed_commit("nonexistent-repo")

        self.assertIsNone(result)

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_get_last_indexed_commit_returns_none_when_never_indexed(self, mock_graph_database):
        """Test get_last_indexed_commit returns None when repo exists but has no SHA."""
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        mock_record = {"sha": None}
        mock_session.run.return_value.single.return_value = mock_record

        result = store.get_last_indexed_commit("repo-123")

        self.assertIsNone(result)

    @patch("clewso_ingestion.graph.GraphDatabase")
    def test_update_last_indexed_commit(self, mock_graph_database):
        """Test update_last_indexed_commit writes SHA to repo node."""
        store = GraphStore()
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        store.update_last_indexed_commit("repo-123", "abc123def456")

        mock_session.run.assert_called_once_with(
            "MATCH (r:Repository {id: $repo_id}) SET r.last_indexed_commit = $sha",
            repo_id="repo-123",
            sha="abc123def456",
        )


if __name__ == "__main__":
    unittest.main()
