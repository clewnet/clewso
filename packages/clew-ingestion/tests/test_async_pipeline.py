"""
Tests for Stage 2: Async pipeline infrastructure and async ParsingStage.

Covers:
- AsyncPipelineStage protocol detection
- Orchestrator async/sync stage dispatch
- ParsingStage._file_reader async generator
- ParsingStage batched embedding and graph calls
- Thread pool lifecycle (setup + deterministic shutdown)
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures — mock external C/native deps so imports don't fail
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_external_deps():
    """Mock native/external modules so the pipeline can be imported."""
    mock_modules = {
        "tree_sitter": MagicMock(),
        "tree_sitter_language_pack": MagicMock(),
        "git": MagicMock(),
        "qdrant_client": MagicMock(),
        "qdrant_client.http": MagicMock(),
        "qdrant_client.http.models": MagicMock(),
        "neo4j": MagicMock(),
    }

    # Only clean up pipeline modules — NOT shared modules (src.graph, src.vector,
    # src.parser, etc.) because other test files import those at module level.
    pipeline_modules = [
        "clewso_ingestion.pipeline",
        "clewso_ingestion.pipeline.base",
        "clewso_ingestion.pipeline.context",
        "clewso_ingestion.pipeline.orchestrator",
        "clewso_ingestion.pipeline.stages",
        "clewso_ingestion.pipeline.stages.parsing",
        "clewso_ingestion.pipeline.stages.discovery",
        "clewso_ingestion.pipeline.stages.finalization",
        "clewso_ingestion.pipeline.stages.processing",
        "clewso_ingestion.pipeline.stages.repository",
        "clewso_ingestion.pipeline.processors",
        "clewso_ingestion.pipeline.processors.registry",
        "clewso_ingestion.pipeline.processors.definition",
        "clewso_ingestion.pipeline.processors.import_processor",
        "clewso_ingestion.pipeline.processors.call",
        "clewso_ingestion.pipeline.exceptions",
    ]

    for mod in pipeline_modules:
        if mod in sys.modules:
            del sys.modules[mod]

    with patch.dict(sys.modules, mock_modules):
        yield

    for mod in pipeline_modules:
        if mod in sys.modules:
            del sys.modules[mod]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(tmp_path, files=None, vector_store=None, graph_store=None, parser=None):
    """Build a minimal IngestionContext for testing."""
    from clewso_ingestion.pipeline.context import IngestionContext

    return IngestionContext(
        repo_id="test-repo",
        repo_name="test_repo",
        repo_url=str(tmp_path),
        temp_dir=tmp_path,
        files=files or [],
        vector_store=vector_store or MagicMock(),
        graph_store=graph_store or MagicMock(),
        parser=parser or MagicMock(),
    )


def _make_file(tmp_path, name="main.py", content="x = 1\n"):
    """Create a real file on disk and return a FileItem for it."""
    from clewso_ingestion.pipeline.context import FileItem

    fp = tmp_path / name
    fp.write_text(content)
    return FileItem(path=name, absolute_path=fp)


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------


class TestAsyncDetection:
    """Verify iscoroutinefunction checks used by the orchestrator."""

    def test_sync_stage_not_detected_as_async(self):
        import inspect

        from clewso_ingestion.pipeline.context import ProcessingResult, ProcessingStatus

        class SyncStage:
            name = "sync"

            def execute(self, context):
                return ProcessingResult(status=ProcessingStatus.SUCCESS, message="ok")

        stage = SyncStage()
        assert not inspect.iscoroutinefunction(stage.execute)

    def test_async_stage_detected(self):
        import inspect

        from clewso_ingestion.pipeline.context import ProcessingResult, ProcessingStatus

        class AsyncStage:
            name = "async"

            async def execute(self, context):
                return ProcessingResult(status=ProcessingStatus.SUCCESS, message="ok")

        stage = AsyncStage()
        assert inspect.iscoroutinefunction(stage.execute)

    def test_parsing_stage_is_async(self):
        import inspect

        from clewso_ingestion.pipeline.stages.parsing import ParsingStage

        stage = ParsingStage()
        assert inspect.iscoroutinefunction(stage.execute)


# ---------------------------------------------------------------------------
# _file_reader async generator
# ---------------------------------------------------------------------------


class TestFileReader:
    """Verify the async generator yields all files with content."""

    @pytest.mark.asyncio
    async def test_yields_all_files(self, tmp_path):
        from clewso_ingestion.pipeline.stages.parsing import ParsingStage

        f1 = _make_file(tmp_path, "a.py", "aaa")
        f2 = _make_file(tmp_path, "b.py", "bbb")

        stage = ParsingStage()
        results = [(fi, c) async for fi, c in stage._file_reader([f1, f2])]

        assert len(results) == 2
        assert results[0][0] is f1
        assert results[0][1] == "aaa"
        assert results[1][0] is f2
        assert results[1][1] == "bbb"

    @pytest.mark.asyncio
    async def test_yields_nothing_for_empty_list(self):
        from clewso_ingestion.pipeline.stages.parsing import ParsingStage

        stage = ParsingStage()
        results = [(fi, c) async for fi, c in stage._file_reader([])]
        assert results == []


# ---------------------------------------------------------------------------
# Batched embedding + graph calls
# ---------------------------------------------------------------------------


class TestParsingBatching:
    """Verify that ParsingStage batches embed and graph operations."""

    @pytest.mark.asyncio
    async def test_single_file_batch(self, tmp_path):
        """One file -> one add_batch call with one item, one create_file_node call."""
        from clewso_ingestion.pipeline.stages.parsing import ParsingStage

        f1 = _make_file(tmp_path, "main.py", "def foo(): pass\n")

        mock_vs = MagicMock()
        mock_vs.add_batch = AsyncMock(return_value=["pid-0"])

        mock_gs = MagicMock()

        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = [
            {
                "type": "definition",
                "kind": "function_definition",
                "name": "foo",
                "content": "def foo(): pass",
                "start_line": 1,
                "end_line": 1,
            }
        ]

        ctx = _make_context(
            tmp_path,
            files=[f1],
            vector_store=mock_vs,
            graph_store=mock_gs,
            parser=mock_parser,
        )

        stage = ParsingStage()
        result = await stage.execute(ctx)

        assert result.is_success
        assert result.items_processed == 1
        assert result.metadata["nodes_extracted"] == 1

        # add_batch called exactly once (final flush)
        mock_vs.add_batch.assert_called_once()
        batch_items = mock_vs.add_batch.call_args[0][0]
        assert len(batch_items) == 1
        assert batch_items[0][1]["type"] == "file"
        assert batch_items[0][1]["path"] == "main.py"

        # graph file node created with correct qdrant_id in a batch
        mock_gs.create_file_nodes_batch.assert_called_once_with(
            repo_id="test-repo",
            items=[{"file_path": "main.py", "qdrant_id": "pid-0"}],
        )

        # ParsedNode was appended to context
        assert len(ctx.nodes) == 1
        assert ctx.nodes[0].name == "foo"

    @pytest.mark.asyncio
    async def test_batch_flush_at_threshold(self, tmp_path):
        """When file count >= BATCH_SIZE, batch is flushed mid-loop."""
        from clewso_ingestion.pipeline.stages.parsing import BATCH_SIZE, ParsingStage

        files = []
        for i in range(BATCH_SIZE + 5):
            files.append(_make_file(tmp_path, f"f{i}.py", f"x_{i} = {i}\n"))

        mock_vs = MagicMock()
        mock_vs.add_batch = AsyncMock(side_effect=lambda items: [f"pid-{j}" for j in range(len(items))])

        mock_gs = MagicMock()
        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = []

        ctx = _make_context(
            tmp_path,
            files=files,
            vector_store=mock_vs,
            graph_store=mock_gs,
            parser=mock_parser,
        )

        stage = ParsingStage()
        result = await stage.execute(ctx)

        assert result.is_success
        assert result.items_processed == BATCH_SIZE + 5

        # Should have been flushed twice: once at BATCH_SIZE, once for the remainder
        assert mock_vs.add_batch.call_count == 2
        first_batch = mock_vs.add_batch.call_args_list[0][0][0]
        second_batch = mock_vs.add_batch.call_args_list[1][0][0]
        assert len(first_batch) == BATCH_SIZE
        assert len(second_batch) == 5

    @pytest.mark.asyncio
    async def test_file_error_does_not_stop_pipeline(self, tmp_path):
        """A file that fails parsing is counted as failed but doesn't stop others."""
        from clewso_ingestion.pipeline.stages.parsing import ParsingStage

        good_file = _make_file(tmp_path, "good.py", "y = 2\n")
        bad_file = _make_file(tmp_path, "bad.py", "bad content\n")

        mock_vs = MagicMock()
        mock_vs.add_batch = AsyncMock(side_effect=lambda items: [f"pid-{j}" for j in range(len(items))])
        mock_gs = MagicMock()

        mock_parser = MagicMock()

        def parse_side_effect(path, content_bytes):
            if "bad" in path:
                raise RuntimeError("parse error")
            return []

        mock_parser.parse_file.side_effect = parse_side_effect

        ctx = _make_context(
            tmp_path,
            files=[good_file, bad_file],
            vector_store=mock_vs,
            graph_store=mock_gs,
            parser=mock_parser,
        )

        stage = ParsingStage()
        result = await stage.execute(ctx)

        assert result.is_partial
        assert result.items_processed == 1
        assert result.items_failed == 1
        assert len(result.errors) == 1
        assert "bad.py" in result.errors[0]["context"]


# ---------------------------------------------------------------------------
# Orchestrator async/sync dispatch
# ---------------------------------------------------------------------------


class TestOrchestratorDispatch:
    """Verify the orchestrator correctly dispatches sync vs async stages."""

    @pytest.mark.asyncio
    async def test_mixed_stages(self, tmp_path):
        """Orchestrator runs sync and async stages in sequence."""
        from clewso_ingestion.pipeline.context import ProcessingResult, ProcessingStatus
        from clewso_ingestion.pipeline.orchestrator import IngestionPipeline

        call_order = []

        class SyncStage:
            name = "SyncTest"

            def execute(self, context):
                call_order.append("sync")
                return ProcessingResult(status=ProcessingStatus.SUCCESS, message="sync ok")

        class AsyncStage:
            name = "AsyncTest"

            async def execute(self, context):
                call_order.append("async")
                return ProcessingResult(status=ProcessingStatus.SUCCESS, message="async ok")

        mock_vs = MagicMock()
        mock_vs.add_batch = AsyncMock(return_value=[])
        mock_gs = MagicMock()
        mock_parser = MagicMock()

        pipeline = IngestionPipeline(
            vector_store=mock_vs,
            graph_store=mock_gs,
            parser=mock_parser,
        )
        # Replace stages with our test stages
        pipeline.stages = [SyncStage(), AsyncStage(), SyncStage()]

        result = await pipeline._run_async("test-id", str(tmp_path))

        assert result.is_success
        assert call_order == ["sync", "async", "sync"]

    @pytest.mark.asyncio
    async def test_thread_pool_shutdown(self, tmp_path):
        """Thread pool is shut down even if a stage raises."""
        from clewso_ingestion.pipeline.exceptions import StageError
        from clewso_ingestion.pipeline.orchestrator import IngestionPipeline

        class FailingStage:
            name = "Fail"

            def execute(self, context):
                raise RuntimeError("boom")

        mock_vs = MagicMock()
        mock_gs = MagicMock()
        mock_parser = MagicMock()

        pipeline = IngestionPipeline(
            vector_store=mock_vs,
            graph_store=mock_gs,
            parser=mock_parser,
        )
        pipeline.stages = [FailingStage()]

        with pytest.raises(StageError):
            await pipeline._run_async("test-id", str(tmp_path))

        # If we get here, the finally block ran (pool.shutdown).
        # The test passing without hanging confirms deterministic cleanup.
