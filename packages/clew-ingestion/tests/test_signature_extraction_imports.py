from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from clewso_ingestion.pipeline.context import IngestionContext, ParsedNode
from clewso_ingestion.pipeline.stages.signature_extraction import SignatureExtractionStage


@pytest.fixture
def context():
    ctx = IngestionContext(
        repo_id="test-repo", repo_name="test-repo", repo_url="http://test.com", temp_dir=Path("/tmp"), files=[]
    )
    ctx.config = {"platform_url": "http://test-platform", "api_key": "test-key"}
    return ctx


@pytest.mark.asyncio
async def test_signature_extraction_with_imports(context):
    # Setup nodes including an import
    export_node = ParsedNode(
        type="function",
        name="my_func",
        content="def my_func(): pass",
        start_line=1,
        end_line=1,
        file_path="src/main.py",
        kind="function_definition",
    )

    import_node = ParsedNode(
        type="import",
        name="os",
        content="import os",
        start_line=2,
        end_line=2,
        file_path="src/main.py",
        kind="import_statement",
    )

    context.nodes = [export_node, import_node]

    stage = SignatureExtractionStage()

    # Mock PlatformClient
    with patch("clewso_ingestion.pipeline.stages.signature_extraction.PlatformClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.send_signatures = AsyncMock(return_value={"links_found": 1, "external_edges": []})
        mock_instance.close = AsyncMock()

        result = await stage.execute(context)

        assert result.status.name == "SUCCESS"
        assert result.metadata["import_count"] == 1
        assert result.metadata["export_count"] == 1

        # Verify call to send_signatures
        mock_instance.send_signatures.assert_called_once()
        call_args = mock_instance.send_signatures.call_args
        _, kwargs = call_args

        assert len(kwargs["exports"]) == 1
        assert len(kwargs["imports"]) == 1
        assert kwargs["imports"][0]["source_module"] == "os"


@pytest.mark.asyncio
async def test_signature_extraction_batching(context):
    # Create > 1000 export nodes to trigger batching
    # Batch size is 1000
    num_nodes = 1500
    context.nodes = [
        ParsedNode(
            type="function",
            name=f"func_{i}",
            content="",
            start_line=i,
            end_line=i,
            file_path=f"src/file_{i}.py",
            kind="function_definition",
        )
        for i in range(num_nodes)
    ]

    stage = SignatureExtractionStage()

    with patch("clewso_ingestion.pipeline.stages.signature_extraction.PlatformClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.send_signatures = AsyncMock(return_value={"links_found": 0, "external_edges": []})
        mock_instance.close = AsyncMock()

        result = await stage.execute(context)

        assert result.status.name == "SUCCESS"
        assert result.metadata["export_count"] == num_nodes

        # Should be called twice: 1 full batch (1000) + 1 partial batch (500)
        assert mock_instance.send_signatures.call_count == 2

        # Check first call
        first_call = mock_instance.send_signatures.call_args_list[0]
        _, kwargs1 = first_call
        assert len(kwargs1["exports"]) == 1000

        # Check second call
        second_call = mock_instance.send_signatures.call_args_list[1]
        _, kwargs2 = second_call
        assert len(kwargs2["exports"]) == 500
