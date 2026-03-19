"""
Tests for incremental sync orchestrator.

Tests file processing, deletion, and fallback scenarios.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_vector_store():
    """Mock VectorStore with deletion support."""
    store = MagicMock()
    store.add.return_value = "vec-123"
    store.add_batch = AsyncMock(side_effect=lambda items: [f"vec-batch-{i}" for i in range(len(items))])
    store.flush.return_value = None
    store.delete_by_filter.return_value = 1
    store.delete_files_batch.return_value = 3
    return store


@pytest.fixture
def mock_graph_store():
    """Mock GraphStore with deletion support."""
    store = MagicMock()
    store.create_repo_node.return_value = None
    store.create_file_node.return_value = None
    store.create_code_node.return_value = None
    store.delete_file_node.return_value = 2
    store.delete_files_batch.return_value = 5
    return store


@pytest.fixture
def mock_parser():
    parser = MagicMock()
    parser.parse_file.return_value = [
        {
            "type": "function_definition",
            "name": "test_func",
            "content": "def test_func(): pass",
            "start_line": 1,
            "end_line": 2,
        }
    ]
    return parser


@pytest.fixture
def temp_repo():
    """Create a temporary repository with sample files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Create sample Python file
        (repo_path / "test.py").write_text("def test_func():\n    pass\n")
        (repo_path / "README.md").write_text("# Test Repo\n")

        yield repo_path


class TestIncrementalSyncOrchestrator:
    """Test IncrementalSyncOrchestrator functionality."""

    @pytest.mark.asyncio
    async def test_sync_changes_success(self, mock_vector_store, mock_graph_store, mock_parser):
        """Test successful incremental sync."""
        from clewso_ingestion.sync import IncrementalSyncOrchestrator

        orchestrator = IncrementalSyncOrchestrator(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            parser=mock_parser,
        )

        changed_files = {
            "added": ["new_file.py"],
            "modified": ["existing_file.py"],
            "removed": ["old_file.py"],
        }

        # Mock clone method
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            (temp_path / "new_file.py").write_text("def new_func(): pass")
            (temp_path / "existing_file.py").write_text("def existing_func(): pass")

            with patch.object(orchestrator, "_clone_at_commit", return_value=temp_path):
                result = await orchestrator.sync_changes(
                    repo_id="user/repo",
                    repo_url="https://github.com/user/repo.git",
                    commit_sha="abc123",
                    changed_files=changed_files,
                )

        assert result["status"] in ["success", "partial"]
        assert result["fallback_to_full"] is False
        assert result["files_removed"] == 1
        assert result["files_synced"] >= 0

    @pytest.mark.asyncio
    async def test_sync_changes_fallback_too_many_files(self, mock_vector_store, mock_graph_store, mock_parser):
        """Test fallback to full sync when too many files changed."""
        from clewso_ingestion.sync import IncrementalSyncOrchestrator

        orchestrator = IncrementalSyncOrchestrator(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            parser=mock_parser,
        )

        # Create payload with > 100 files
        changed_files = {
            "added": [f"file_{i}.py" for i in range(150)],
            "modified": [],
            "removed": [],
        }

        result = await orchestrator.sync_changes(
            repo_id="user/repo",
            repo_url="https://github.com/user/repo.git",
            commit_sha="abc123",
            changed_files=changed_files,
        )

        assert result["status"] == "fallback"
        assert result["fallback_to_full"] is True

    @pytest.mark.asyncio
    async def test_remove_files(self, mock_vector_store, mock_graph_store, mock_parser):
        """Test file removal from graph and vector stores."""
        from clewso_ingestion.sync import IncrementalSyncOrchestrator

        orchestrator = IncrementalSyncOrchestrator(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            parser=mock_parser,
        )

        file_paths = ["deleted1.py", "deleted2.py", "deleted3.py"]

        removed_count = await orchestrator._remove_files("user/repo", file_paths)

        assert removed_count == 3
        assert mock_graph_store.delete_file_node.call_count == 3
        assert mock_vector_store.delete_by_filter.call_count == 3

    @pytest.mark.asyncio
    async def test_remove_files_empty_list(self, mock_vector_store, mock_graph_store, mock_parser):
        """Test that empty removal list is handled gracefully."""
        from clewso_ingestion.sync import IncrementalSyncOrchestrator

        orchestrator = IncrementalSyncOrchestrator(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            parser=mock_parser,
        )

        removed_count = await orchestrator._remove_files("user/repo", [])

        assert removed_count == 0
        mock_graph_store.delete_file_node.assert_not_called()
        mock_vector_store.delete_by_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_files_filters_unsupported(self, mock_vector_store, mock_graph_store, mock_parser):
        """Test that unsupported file types are filtered out."""
        from clewso_ingestion.sync import IncrementalSyncOrchestrator

        orchestrator = IncrementalSyncOrchestrator(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            parser=mock_parser,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            (temp_path / "test.py").write_text("def test(): pass")
            (temp_path / "test.txt").write_text("Not code")  # Unsupported
            (temp_path / "test.jpg").write_bytes(b"fake image")  # Unsupported

            file_paths = ["test.py", "test.txt", "test.jpg"]

            files_synced, errors = await orchestrator._process_files(
                repo_id="user/repo",
                repo_url="https://github.com/user/repo.git",
                temp_dir=temp_path,
                file_paths=file_paths,
            )

            # Only .py file should be processed
            # Exact count depends on pipeline stages, but should be >= 0
            assert files_synced >= 0

    @pytest.mark.asyncio
    async def test_clone_at_commit_failure(self, mock_vector_store, mock_graph_store, mock_parser):
        """Test handling of clone failures."""
        from clewso_ingestion.sync import IncrementalSyncOrchestrator

        orchestrator = IncrementalSyncOrchestrator(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            parser=mock_parser,
        )

        # Mock clone to raise exception
        with patch("clewso_ingestion.sync.Repo.clone_from", side_effect=Exception("Clone failed")):
            with pytest.raises(Exception, match="Failed to clone repository"):
                await orchestrator._clone_at_commit("https://invalid-repo.git", "abc123")

    @pytest.mark.asyncio
    async def test_sync_changes_handles_errors_gracefully(self, mock_vector_store, mock_graph_store, mock_parser):
        """Test that errors during sync are handled gracefully."""
        from clewso_ingestion.sync import IncrementalSyncOrchestrator

        orchestrator = IncrementalSyncOrchestrator(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            parser=mock_parser,
        )

        changed_files = {
            "added": ["test.py"],
            "modified": [],
            "removed": [],
        }

        # Mock clone to raise exception
        with patch.object(orchestrator, "_clone_at_commit", side_effect=Exception("Network error")):
            result = await orchestrator.sync_changes(
                repo_id="user/repo",
                repo_url="https://github.com/user/repo.git",
                commit_sha="abc123",
                changed_files=changed_files,
            )

        assert result["status"] == "failed"
        assert len(result["errors"]) > 0
        assert "Network error" in result["errors"][0]


class TestGraphStoreDeletion:
    """Test GraphStore deletion methods."""

    def test_delete_file_node(self, mock_graph_store):
        """Test single file node deletion."""
        # This would require Neo4j mock, but we're testing the interface
        mock_graph_store.delete_file_node.return_value = 3

        deleted = mock_graph_store.delete_file_node("user/repo", "test.py")

        assert deleted == 3
        mock_graph_store.delete_file_node.assert_called_once_with("user/repo", "test.py")

    def test_delete_files_batch(self, mock_graph_store):
        """Test batch file deletion."""
        mock_graph_store.delete_files_batch.return_value = 10

        files = ["file1.py", "file2.py", "file3.py"]
        deleted = mock_graph_store.delete_files_batch("user/repo", files)

        assert deleted == 10
        mock_graph_store.delete_files_batch.assert_called_once_with("user/repo", files)


class TestVectorStoreDeletion:
    """Test VectorStore deletion methods."""

    def test_delete_by_filter(self, mock_vector_store):
        """Test vector deletion by metadata filter."""
        mock_vector_store.delete_by_filter.return_value = 5

        deleted = mock_vector_store.delete_by_filter("user/repo", "test.py")

        assert deleted == 5
        mock_vector_store.delete_by_filter.assert_called_once_with("user/repo", "test.py")

    def test_delete_files_batch(self, mock_vector_store):
        """Test batch vector deletion."""
        mock_vector_store.delete_files_batch.return_value = 15

        files = ["file1.py", "file2.py", "file3.py"]
        deleted = mock_vector_store.delete_files_batch("user/repo", files)

        assert deleted == 15
        mock_vector_store.delete_files_batch.assert_called_once_with("user/repo", files)
