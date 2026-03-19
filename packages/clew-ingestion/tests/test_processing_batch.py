"""
Tests for the batched ProcessingStage (Stage 3).

Verifies:
- Batched path collects and flushes embed items + graph ops correctly
- qdrant_id values flow from add_batch through to graph operations
- Per-node fallback path still works via config flag
- Partial failure handling
- Batch size boundary flushing
"""

import sys
from pathlib import Path
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


def _make_context(mock_vector_store, mock_graph_store, nodes=None, config=None):
    from clewso_ingestion.pipeline.context import IngestionContext

    ctx = IngestionContext(
        repo_id="test-repo",
        repo_name="test",
        repo_url="/tmp/test",
        temp_dir=Path("/tmp/test"),
        vector_store=mock_vector_store,
        graph_store=mock_graph_store,
        parser=MagicMock(),
        config=config or {},
    )
    if nodes:
        ctx.nodes = nodes
    return ctx


def _def_node(name="my_func", kind="function", file_path="src/main.py"):
    from clewso_ingestion.pipeline.context import ParsedNode

    return ParsedNode(
        type="definition",
        kind=kind,
        name=name,
        content=f"def {name}(): pass",
        start_line=1,
        end_line=2,
        file_path=file_path,
    )


def _import_node(name="os", file_path="src/main.py"):
    from clewso_ingestion.pipeline.context import ParsedNode

    return ParsedNode(
        type="import",
        kind="import_statement",
        name=name,
        content=f"import {name}",
        start_line=1,
        end_line=1,
        file_path=file_path,
    )


def _call_node(name="print", file_path="src/main.py"):
    from clewso_ingestion.pipeline.context import ParsedNode

    return ParsedNode(
        type="call",
        kind="call_expression",
        name=name,
        content=f"{name}()",
        start_line=3,
        end_line=3,
        file_path=file_path,
    )


@pytest.fixture
def mock_vector_store():
    store = MagicMock()
    # Explicitly set as AsyncMock to handle 'await' in ProcessingStage
    store.add_batch = AsyncMock(
        side_effect=lambda items: [item[2] if len(item) == 3 else f"gen-{i}" for i, item in enumerate(items)]
    )
    store.flush = AsyncMock()
    store._batch_size = 100
    return store


@pytest.fixture
def mock_graph_store():
    store = MagicMock()
    store.execute_batch = MagicMock()
    return store


@pytest.fixture
def processing_stage():
    from clewso_ingestion.pipeline.processors.registry import NodeProcessorRegistry
    from clewso_ingestion.pipeline.stages.processing import ProcessingStage

    return ProcessingStage(NodeProcessorRegistry())


# ---------------------------------------------------------------------------
# Tests — Batched path (default)
# ---------------------------------------------------------------------------


class TestBatchedProcessing:
    @pytest.mark.asyncio
    async def test_processes_definition_nodes(self, processing_stage, mock_vector_store, mock_graph_store):
        """Definition nodes should produce both embed items and graph ops."""
        from clewso_ingestion.pipeline.stages.processing import _CREATE_CODE_NODE_CYPHER

        nodes = [_def_node("func_a"), _def_node("func_b", kind="class")]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        result = await processing_stage.execute(ctx)

        from clewso_ingestion.pipeline.context import ProcessingStatus

        assert result.status == ProcessingStatus.SUCCESS
        assert result.items_processed == 2

        # add_batch should have been called with 2 items
        mock_vector_store.add_batch.assert_awaited_once()
        embed_call_items = mock_vector_store.add_batch.call_args[0][0]
        assert len(embed_call_items) == 2
        assert embed_call_items[0][0] == "def func_a(): pass"
        assert embed_call_items[1][0] == "def func_b(): pass"

        # execute_batch should have been called with 2 graph ops
        mock_graph_store.execute_batch.assert_called_once()
        graph_ops = mock_graph_store.execute_batch.call_args[0][0]
        assert len(graph_ops) == 2
        assert graph_ops[0][0] == _CREATE_CODE_NODE_CYPHER
        assert graph_ops[0][1]["name"] == "func_a"
        assert graph_ops[1][1]["name"] == "func_b"

    @pytest.mark.asyncio
    async def test_processes_import_nodes(self, processing_stage, mock_vector_store, mock_graph_store):
        """Import nodes should produce only graph ops (no embeddings)."""
        from clewso_ingestion.pipeline.context import ProcessingStatus
        from clewso_ingestion.pipeline.stages.processing import _CREATE_IMPORT_CYPHER

        nodes = [_import_node("mymodule"), _import_node("app_utils")]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        result = await processing_stage.execute(ctx)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.items_processed == 2

        # No embeddings for imports
        mock_vector_store.add_batch.assert_not_awaited()

        # Graph ops for imports
        mock_graph_store.execute_batch.assert_called_once()
        graph_ops = mock_graph_store.execute_batch.call_args[0][0]
        assert len(graph_ops) == 2
        assert graph_ops[0][0] == _CREATE_IMPORT_CYPHER
        assert graph_ops[0][1]["module_name"] == "mymodule"
        assert graph_ops[1][1]["module_name"] == "app_utils"

    @pytest.mark.asyncio
    async def test_processes_call_nodes(self, processing_stage, mock_vector_store, mock_graph_store):
        """Call nodes should produce only graph ops (no embeddings)."""
        from clewso_ingestion.pipeline.context import ProcessingStatus
        from clewso_ingestion.pipeline.stages.processing import _CREATE_CALL_CYPHER

        nodes = [_call_node("print"), _call_node("len")]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        result = await processing_stage.execute(ctx)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.items_processed == 2

        mock_vector_store.add_batch.assert_not_awaited()

        mock_graph_store.execute_batch.assert_called_once()
        graph_ops = mock_graph_store.execute_batch.call_args[0][0]
        assert len(graph_ops) == 2
        assert graph_ops[0][0] == _CREATE_CALL_CYPHER
        assert graph_ops[0][1]["target_name"] == "print"

    @pytest.mark.asyncio
    async def test_mixed_node_types(self, processing_stage, mock_vector_store, mock_graph_store):
        """Processing mixed node types in one batch."""
        from clewso_ingestion.pipeline.context import ProcessingStatus

        nodes = [
            _def_node("my_func"),
            _import_node("mymodule"),
            _call_node("print"),
        ]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        result = await processing_stage.execute(ctx)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.items_processed == 3

        # 1 definition -> 1 embed item
        embed_call_items = mock_vector_store.add_batch.call_args[0][0]
        assert len(embed_call_items) == 1

        # 3 total graph ops (1 def + 1 import + 1 call)
        graph_ops = mock_graph_store.execute_batch.call_args[0][0]
        assert len(graph_ops) == 3

    @pytest.mark.asyncio
    async def test_qdrant_id_flows_to_graph_ops(self, processing_stage, mock_vector_store, mock_graph_store):
        """The pre-generated qdrant_id must appear in both embed items and graph params."""
        nodes = [_def_node("func_a")]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        await processing_stage.execute(ctx)

        embed_items = mock_vector_store.add_batch.call_args[0][0]
        graph_ops = mock_graph_store.execute_batch.call_args[0][0]

        # The qdrant_id in the embed item (3rd element) must match the one in graph params
        embed_qdrant_id = embed_items[0][2]
        graph_qdrant_id = graph_ops[0][1]["qdrant_id"]

        assert embed_qdrant_id == graph_qdrant_id
        # Should be a valid UUID string
        assert len(embed_qdrant_id) == 36  # UUID format: 8-4-4-4-12

    @pytest.mark.asyncio
    async def test_batch_flushing_at_threshold(self, processing_stage, mock_vector_store, mock_graph_store):
        """Nodes should be flushed in batches when reaching the batch size."""
        # Create 75 import nodes with batch_size=50 -> should flush once mid-loop + once at end
        nodes = [_import_node(f"mod_{i}") for i in range(75)]
        ctx = _make_context(
            mock_vector_store,
            mock_graph_store,
            nodes=nodes,
            config={"processing_batch_size": 50},
        )

        from clewso_ingestion.pipeline.context import ProcessingStatus

        result = await processing_stage.execute(ctx)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.items_processed == 75

        # execute_batch should be called twice: once at 50, once for remaining 25
        assert mock_graph_store.execute_batch.call_count == 2
        first_batch = mock_graph_store.execute_batch.call_args_list[0][0][0]
        second_batch = mock_graph_store.execute_batch.call_args_list[1][0][0]
        assert len(first_batch) == 50
        assert len(second_batch) == 25

    @pytest.mark.asyncio
    async def test_empty_nodes_list(self, processing_stage, mock_vector_store, mock_graph_store):
        """Empty nodes list should return success with 0 processed."""
        from clewso_ingestion.pipeline.context import ProcessingStatus

        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=[])

        result = await processing_stage.execute(ctx)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.items_processed == 0
        mock_vector_store.add_batch.assert_not_awaited()
        mock_graph_store.execute_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_failure_produces_partial_status(self, processing_stage, mock_vector_store, mock_graph_store):
        """If batch flush fails, status should be PARTIAL when some nodes were collected."""
        from clewso_ingestion.pipeline.context import ProcessingStatus

        mock_graph_store.execute_batch.side_effect = Exception("Neo4j down")

        nodes = [_import_node("mymodule")]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        result = await processing_stage.execute(ctx)

        # Node was counted as processed before the flush failed
        assert result.items_processed == 1
        assert len(result.errors) > 0
        assert result.status == ProcessingStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_definition_metadata_correctness(self, processing_stage, mock_vector_store, mock_graph_store):
        """Verify the metadata dict passed to add_batch is correct."""
        node = _def_node("calculate", kind="function", file_path="lib/math.py")
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=[node])

        await processing_stage.execute(ctx)

        embed_items = mock_vector_store.add_batch.call_args[0][0]
        metadata = embed_items[0][1]
        assert metadata["path"] == "lib/math.py"
        assert metadata["repo_id"] == "test-repo"
        assert metadata["name"] == "calculate"
        assert metadata["type"] == "function"

    @pytest.mark.asyncio
    async def test_graph_params_correctness(self, processing_stage, mock_vector_store, mock_graph_store):
        """Verify the Cypher params for each node type are correct."""
        nodes = [
            _def_node("my_func", kind="function", file_path="a.py"),
            _import_node("mymodule", file_path="a.py"),
            _call_node("print", file_path="a.py"),
        ]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        await processing_stage.execute(ctx)

        graph_ops = mock_graph_store.execute_batch.call_args[0][0]

        # Definition params
        def_params = graph_ops[0][1]
        assert def_params["repo_id"] == "test-repo"
        assert def_params["file_path"] == "a.py"
        assert def_params["name"] == "my_func"
        assert def_params["node_type"] == "function"
        assert def_params["start_line"] == 1
        assert def_params["end_line"] == 2
        assert "qdrant_id" in def_params

        # Import params
        import_params = graph_ops[1][1]
        assert import_params["repo_id"] == "test-repo"
        assert import_params["file_path"] == "a.py"
        assert import_params["module_name"] == "mymodule"

        # Call params
        call_params = graph_ops[2][1]
        assert call_params["repo_id"] == "test-repo"
        assert call_params["file_path"] == "a.py"
        assert call_params["target_name"] == "print"


# ---------------------------------------------------------------------------
# Tests — Per-node fallback path
# ---------------------------------------------------------------------------


class TestPerNodeFallback:
    @pytest.mark.asyncio
    async def test_per_node_path_via_config(self, mock_vector_store, mock_graph_store):
        """Setting batch_processing=False should use the per-node registry path."""
        from clewso_ingestion.pipeline.context import ProcessingStatus
        from clewso_ingestion.pipeline.processors import (
            CallProcessor,
            DefinitionProcessor,
            ImportProcessor,
        )
        from clewso_ingestion.pipeline.processors.registry import NodeProcessorRegistry
        from clewso_ingestion.pipeline.stages.processing import ProcessingStage

        registry = NodeProcessorRegistry()
        registry.register("definition", DefinitionProcessor())
        registry.register("import", ImportProcessor())
        registry.register("call", CallProcessor())

        stage = ProcessingStage(registry)

        nodes = [
            _def_node("func_a"),
            _import_node("mymodule"),
            _call_node("print"),
        ]
        mock_vector_store.add_batch = AsyncMock(return_value=["id1", "id2", "id3"])
        ctx = _make_context(
            mock_vector_store,
            mock_graph_store,
            nodes=nodes,
            config={"batch_processing": False},
        )

        result = await stage.execute(ctx)

        assert result.items_processed == 3
        assert result.status == ProcessingStatus.SUCCESS

        # Per-node path uses individual graph store calls, not execute_batch
        mock_graph_store.execute_batch.assert_not_called()
        # Import and call processors call individual methods
        mock_graph_store.create_import_relationship.assert_called_once()
        mock_graph_store.create_call_relationship.assert_called_once()
        # Definition processor buffers vectors rather than calling add_batch directly
        assert len(ctx.vector_buffer) == 0  # flushed at end

    @pytest.mark.asyncio
    async def test_batched_is_default(self, processing_stage, mock_vector_store, mock_graph_store):
        """When no config is set, batched path should be used by default."""
        nodes = [_import_node("mymodule")]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        await processing_stage.execute(ctx)

        # Batched path uses execute_batch, not individual methods
        mock_graph_store.execute_batch.assert_called_once()
        mock_graph_store.create_import_relationship.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — Multiple qdrant_id correctness across batch
# ---------------------------------------------------------------------------


class TestQdrantIdPlumbing:
    @pytest.mark.asyncio
    async def test_multiple_definitions_unique_ids(self, processing_stage, mock_vector_store, mock_graph_store):
        """Each definition should get a unique qdrant_id that matches between embed and graph."""
        nodes = [_def_node(f"func_{i}") for i in range(5)]
        ctx = _make_context(mock_vector_store, mock_graph_store, nodes=nodes)

        await processing_stage.execute(ctx)

        embed_items = mock_vector_store.add_batch.call_args[0][0]
        graph_ops = mock_graph_store.execute_batch.call_args[0][0]

        embed_ids = [item[2] for item in embed_items]
        graph_ids = [op[1]["qdrant_id"] for op in graph_ops]

        # All IDs should be unique
        assert len(set(embed_ids)) == 5

        # Embed IDs and graph IDs should match in order
        assert embed_ids == graph_ids

    @pytest.mark.asyncio
    async def test_ids_preserved_across_batch_boundaries(self, processing_stage, mock_vector_store, mock_graph_store):
        """qdrant_ids should be correctly paired even when batches are flushed mid-loop."""
        # 4 definitions with batch_size=2 -> 2 flushes
        nodes = [_def_node(f"func_{i}") for i in range(4)]
        ctx = _make_context(
            mock_vector_store,
            mock_graph_store,
            nodes=nodes,
            config={"processing_batch_size": 2},
        )

        await processing_stage.execute(ctx)

        # Should have 2 flush calls
        assert mock_vector_store.add_batch.await_count == 2
        assert mock_graph_store.execute_batch.call_count == 2

        # Check each batch: embed IDs match graph IDs
        for call_idx in range(2):
            embed_items = mock_vector_store.add_batch.call_args_list[call_idx][0][0]
            graph_ops = mock_graph_store.execute_batch.call_args_list[call_idx][0][0]

            for embed_item, graph_op in zip(embed_items, graph_ops, strict=True):
                assert embed_item[2] == graph_op[1]["qdrant_id"]
