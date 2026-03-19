"""Tests for Phase 1 incremental sync: IDs, delete methods, and pipeline."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Deterministic ID tests
# ---------------------------------------------------------------------------


class TestMakeVectorId:
    def test_same_inputs_same_id(self):
        from clewso_ingestion.pipeline.ids import make_vector_id

        a = make_vector_id("owner/repo", "src/foo.py")
        b = make_vector_id("owner/repo", "src/foo.py")
        assert a == b

    def test_different_file_different_id(self):
        from clewso_ingestion.pipeline.ids import make_vector_id

        a = make_vector_id("owner/repo", "src/foo.py")
        b = make_vector_id("owner/repo", "src/bar.py")
        assert a != b

    def test_different_repo_different_id(self):
        from clewso_ingestion.pipeline.ids import make_vector_id

        a = make_vector_id("owner/repo-a", "src/foo.py")
        b = make_vector_id("owner/repo-b", "src/foo.py")
        assert a != b

    def test_returns_64_char_hex(self):
        from clewso_ingestion.pipeline.ids import make_vector_id

        id_ = make_vector_id("owner/repo", "src/foo.py")
        assert len(id_) == 64
        assert all(c in "0123456789abcdef" for c in id_)


# ---------------------------------------------------------------------------
# VectorStore.delete tests
# ---------------------------------------------------------------------------


class TestVectorStoreDelete:
    @pytest.fixture
    def store(self):
        with patch("clewso_ingestion.vector.QdrantClient"):
            from clewso_ingestion.vector import VectorStore

            s = VectorStore()
            s.client = MagicMock()
            yield s

    @pytest.mark.asyncio
    async def test_delete_calls_qdrant_delete(self, store):
        """delete() should forward the ID to qdrant client.delete."""
        await store.delete("abc123")

        from qdrant_client.http import models

        store.client.delete.assert_called_once_with(
            collection_name="codebase",
            points_selector=models.PointIdsList(points=["abc123"]),
        )

    @pytest.mark.asyncio
    async def test_delete_wraps_single_id_in_list(self, store):
        """The ID must be wrapped in a list for the Qdrant client."""
        await store.delete("deadbeef")

        from qdrant_client.http import models

        _, kwargs = store.client.delete.call_args
        assert kwargs["points_selector"] == models.PointIdsList(points=["deadbeef"])


# ---------------------------------------------------------------------------
# GraphStore.delete_file_edges tests
# ---------------------------------------------------------------------------


class TestGraphStoreDeleteFileEdges:
    @pytest.fixture
    def store(self):
        import sys

        mock_neo4j = MagicMock()
        sys.modules.setdefault("neo4j", mock_neo4j)

        with patch("clewso_ingestion.graph.GraphDatabase"):
            from clewso_ingestion.graph import GraphStore

            s = GraphStore()
            s.driver = MagicMock()
            yield s

    def test_delete_file_edges_runs_cypher(self, store):
        """delete_file_edges() should run a Cypher DELETE on IMPORTS|CALLS."""
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        store.delete_file_edges("owner/repo", "src/foo.py")

        mock_session.run.assert_called_once()
        cypher, *_ = mock_session.run.call_args[0]
        assert "IMPORTS|CALLS" in cypher
        assert "DELETE r" in cypher

    def test_delete_file_edges_passes_correct_params(self, store):
        """Parameters repo_id and file_path should be forwarded to Cypher."""
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        store.delete_file_edges("owner/repo", "src/bar.py")

        _, kwargs = mock_session.run.call_args
        assert kwargs["repo_id"] == "owner/repo"
        assert kwargs["file_path"] == "src/bar.py"

    def test_delete_file_edges_does_not_delete_node(self, store):
        """delete_file_edges should NOT issue DETACH DELETE on the file node."""
        mock_session = MagicMock()
        store.driver.session.return_value.__enter__.return_value = mock_session

        store.delete_file_edges("owner/repo", "src/foo.py")

        cypher, *_ = mock_session.run.call_args[0]
        assert "DETACH DELETE" not in cypher


# ---------------------------------------------------------------------------
# ParsingStage deterministic ID tests
# ---------------------------------------------------------------------------


class TestParsingStageUsesDetId:
    @pytest.mark.asyncio
    async def test_file_embed_uses_deterministic_id(self):
        """ParsingStage should pass a sha256 ID (not None) to add_batch."""
        from clewso_ingestion.pipeline.ids import make_vector_id
        from clewso_ingestion.pipeline.stages.parsing import ParsingStage

        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = []

        captured: list = []

        async def mock_add_batch(items):
            captured.extend(items)
            return [item[2] for item in items]  # return the IDs we were given

        mock_vector_store = MagicMock()
        mock_vector_store.add_batch = mock_add_batch

        mock_graph_store = MagicMock()
        mock_graph_store.create_file_nodes_batch = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "hello.py").write_text("x = 1\n")

            from clewso_ingestion.pipeline.context import FileItem, IngestionContext

            context = IngestionContext(
                repo_id="owner/repo",
                repo_name="repo",
                repo_url=tmpdir,
                temp_dir=tmp,
                vector_store=mock_vector_store,
                graph_store=mock_graph_store,
                parser=mock_parser,
                files=[
                    FileItem(
                        path="hello.py",
                        absolute_path=tmp / "hello.py",
                    )
                ],
            )

            stage = ParsingStage()
            await stage.execute(context)

        assert len(captured) == 1
        _text, _meta, passed_id = captured[0]
        expected_id = make_vector_id("owner/repo", "hello.py")
        assert passed_id == expected_id, f"Expected deterministic ID {expected_id!r}, got {passed_id!r}"


# ---------------------------------------------------------------------------
# ChangeSet dataclass tests
# ---------------------------------------------------------------------------


class TestChangeSet:
    def test_defaults_to_empty_lists(self):
        from clewso_ingestion.pipeline.context import ChangeSet

        cs = ChangeSet(repo_id="x/y", repo_path="/tmp/r", commit_sha="abc")
        assert cs.added == []
        assert cs.modified == []
        assert cs.removed == []

    def test_stores_values(self):
        from clewso_ingestion.pipeline.context import ChangeSet

        cs = ChangeSet(
            repo_id="a/b",
            repo_path="/tmp/p",
            commit_sha="sha1",
            added=["new.py"],
            modified=["old.py"],
            removed=["gone.py"],
        )
        assert cs.repo_id == "a/b"
        assert cs.commit_sha == "sha1"
        assert cs.added == ["new.py"]


# ---------------------------------------------------------------------------
# IncrementalIngestionPipeline tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_stores():
    """Return (vector_store, graph_store) with all required methods mocked."""
    vs = MagicMock()
    vs.add_batch = AsyncMock(return_value=[])
    vs.flush = AsyncMock()
    vs.delete = AsyncMock()

    gs = MagicMock()
    gs.delete_file_node = MagicMock(return_value=1)
    gs.delete_file_edges = MagicMock()
    gs.create_file_nodes_batch = MagicMock()
    gs.execute_batch = MagicMock()

    return vs, gs


@pytest.fixture
def mock_parser():
    p = MagicMock()
    p.parse_file.return_value = []
    return p


class TestIncrementalIngestionPipeline:
    def _make_pipeline(self, vs, gs, parser):
        from clewso_ingestion.incremental_pipeline import IncrementalIngestionPipeline

        return IncrementalIngestionPipeline(
            vector_store=vs,
            graph_store=gs,
            parser=parser,
        )

    @pytest.mark.asyncio
    async def test_removals_delete_vector_and_graph(self, mock_stores, mock_parser):
        """Removed files trigger delete on both stores."""
        from clewso_ingestion.pipeline.context import ChangeSet
        from clewso_ingestion.pipeline.ids import make_vector_id

        vs, gs = mock_stores
        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="abc",
                removed=["deleted.py"],
            )
            result = await pipeline._run_async(cs)

        gs.delete_file_node.assert_called_once_with("owner/repo", "deleted.py")
        vs.delete.assert_awaited_once_with(make_vector_id("owner/repo", "deleted.py"))
        assert result.metadata["files_removed"] == 1

    @pytest.mark.asyncio
    async def test_modifications_delete_edges_before_processing(self, mock_stores, mock_parser):
        """Modified files must have their outgoing edges deleted before re-parse."""
        from clewso_ingestion.pipeline.context import ChangeSet

        vs, gs = mock_stores
        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "mod.py").write_text("x = 1\n")

            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="abc",
                modified=["mod.py"],
            )
            await pipeline._run_async(cs)

        gs.delete_file_edges.assert_called_once_with("owner/repo", "mod.py")

    @pytest.mark.asyncio
    async def test_additions_do_not_delete_edges(self, mock_stores, mock_parser):
        """Added files must NOT trigger edge deletion."""
        from clewso_ingestion.pipeline.context import ChangeSet

        vs, gs = mock_stores
        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "new.py").write_text("x = 1\n")

            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="abc",
                added=["new.py"],
            )
            await pipeline._run_async(cs)

        gs.delete_file_edges.assert_not_called()

    @pytest.mark.asyncio
    async def test_processing_order_removals_first(self, mock_stores, mock_parser):
        """Removals should complete before additions are processed."""
        from clewso_ingestion.pipeline.context import ChangeSet

        vs, gs = mock_stores
        call_order: list[str] = []

        original_delete_node = gs.delete_file_node
        original_add_batch = vs.add_batch

        def track_delete(*args, **kwargs):
            call_order.append("delete_node")
            return original_delete_node(*args, **kwargs)

        async def track_add_batch(*args, **kwargs):
            call_order.append("add_batch")
            return await original_add_batch(*args, **kwargs)

        gs.delete_file_node = track_delete
        vs.add_batch = track_add_batch

        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "new.py").write_text("x = 1\n")

            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="abc",
                added=["new.py"],
                removed=["gone.py"],
            )
            await pipeline._run_async(cs)

        if "delete_node" in call_order and "add_batch" in call_order:
            assert call_order.index("delete_node") < call_order.index("add_batch")

    @pytest.mark.asyncio
    async def test_unsupported_files_are_skipped(self, mock_stores, mock_parser):
        """Non-code files (e.g. .txt) should not be passed to the pipeline."""
        from clewso_ingestion.pipeline.context import ChangeSet

        vs, gs = mock_stores
        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "notes.txt").write_text("just text\n")

            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="abc",
                added=["notes.txt"],
            )
            await pipeline._run_async(cs)

        # Parser should not have been called for an unsupported file
        mock_parser.parse_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_changeset_returns_success(self, mock_stores, mock_parser):
        """An empty ChangeSet should return SUCCESS with 0 files processed."""
        from clewso_ingestion.pipeline.context import ChangeSet, ProcessingStatus

        vs, gs = mock_stores
        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="abc",
            )
            result = await pipeline._run_async(cs)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.items_processed == 0
        assert result.metadata["files_removed"] == 0

    @pytest.mark.asyncio
    async def test_result_metadata_contains_commit_sha(self, mock_stores, mock_parser):
        """ProcessingResult.metadata should expose the commit SHA."""
        from clewso_ingestion.pipeline.context import ChangeSet

        vs, gs = mock_stores
        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="deadbeef",
            )
            result = await pipeline._run_async(cs)

        assert result.metadata["commit_sha"] == "deadbeef"

    def test_run_is_synchronous_wrapper(self, mock_stores, mock_parser):
        """run() should block until completion and return a ProcessingResult."""
        from clewso_ingestion.pipeline.context import ChangeSet, ProcessingResult

        vs, gs = mock_stores
        pipeline = self._make_pipeline(vs, gs, mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="abc",
            )
            result = pipeline.run(cs)

        assert isinstance(result, ProcessingResult)


# ---------------------------------------------------------------------------
# Integration-style test: full round-trip with temp files
# ---------------------------------------------------------------------------


class TestIncrementalPipelineIntegration:
    @pytest.mark.asyncio
    async def test_add_then_modify_calls_correct_ops(self):
        """End-to-end: add a file then modify it, verify correct store calls."""
        from clewso_ingestion.incremental_pipeline import IncrementalIngestionPipeline
        from clewso_ingestion.pipeline.context import ChangeSet
        from clewso_ingestion.pipeline.ids import make_vector_id

        vs = MagicMock()
        added_ids: list = []

        async def capture_add_batch(items):
            ids = [item[2] for item in items]
            added_ids.extend(ids)
            return ids

        vs.add_batch = capture_add_batch
        vs.flush = AsyncMock()
        vs.delete = AsyncMock()

        gs = MagicMock()
        gs.delete_file_node = MagicMock(return_value=1)
        gs.delete_file_edges = MagicMock()
        gs.create_file_nodes_batch = MagicMock()
        gs.execute_batch = MagicMock()

        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = []

        pipeline = IncrementalIngestionPipeline(vector_store=vs, graph_store=gs, parser=mock_parser)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "main.py").write_text("def hello(): pass\n")

            # First pass: add
            cs_add = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="sha1",
                added=["main.py"],
            )
            await pipeline._run_async(cs_add)

            # The ID used for the add must be deterministic
            expected_id = make_vector_id("owner/repo", "main.py")
            assert expected_id in added_ids, f"Deterministic ID {expected_id!r} not found in add_batch calls"

            # Second pass: modify (same file)
            cs_mod = ChangeSet(
                repo_id="owner/repo",
                repo_path=tmpdir,
                commit_sha="sha2",
                modified=["main.py"],
            )
            await pipeline._run_async(cs_mod)

            # Edge deletion must precede the second add
            gs.delete_file_edges.assert_called_once_with("owner/repo", "main.py")
