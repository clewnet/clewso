"""Tests for protocol conformance — verify existing and new stores satisfy protocols."""

from clewso_core.protocols import GraphWriter, VectorWriter


def test_ladybug_satisfies_graph_writer():
    from clew.server.adapters.ladybug import LadybugUnifiedStore

    store = LadybugUnifiedStore(":memory:", embedding_dimension=4)
    assert isinstance(store, GraphWriter)


def test_ladybug_satisfies_vector_writer():
    from clew.server.adapters.ladybug import LadybugUnifiedStore

    store = LadybugUnifiedStore(":memory:", embedding_dimension=4)
    assert isinstance(store, VectorWriter)
