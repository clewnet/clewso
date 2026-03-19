from unittest.mock import patch

import pytest

from clew.server.adapters.reranker import CrossEncoderReranker, NoOpReranker


@pytest.mark.asyncio
async def test_no_op_reranker():
    reranker = NoOpReranker()
    query = "test query"
    docs = ["doc1", "doc2", "doc3"]
    scores = await reranker.rerank(query, docs)
    assert scores == [1.0, 1.0, 1.0]


@pytest.mark.asyncio
async def test_cross_encoder_reranker_mock():
    # Mock CrossEncoder to avoid loading the model during test
    with patch("clew.server.adapters.reranker.CrossEncoder") as MockEncoder:
        mock_instance = MockEncoder.return_value
        mock_instance.predict.return_value = [0.9, 0.1, 0.5]

        reranker = CrossEncoderReranker()
        query = "test query"
        docs = ["doc1", "doc2", "doc3"]

        scores = await reranker.rerank(query, docs)

        assert scores == [0.9, 0.1, 0.5]
        assert mock_instance.predict.called


@pytest.mark.asyncio
async def test_cross_encoder_reranker_fallback():
    # Test fallback when CrossEncoder is not available
    with patch("clew.server.adapters.reranker.CrossEncoder", None):
        reranker = CrossEncoderReranker()
        query = "test query"
        docs = ["doc1", "doc2"]
        scores = await reranker.rerank(query, docs)
        assert len(scores) == 2
        # Initial scores should be decreasing
        assert scores[0] > scores[1]
