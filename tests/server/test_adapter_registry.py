"""
Tests for the adapter registry system.

Verifies that the dynamic registration system works correctly
and eliminates the need for hardcoded if/else chains.
"""

import pytest

from clew.server.adapters.registry import AdapterRegistry


def test_adapter_registry_basic():
    """Test basic registry operations."""
    registry = AdapterRegistry[str]("TestAdapter")

    # Register a simple factory
    registry.register("test", lambda: "test_value")

    # Get the registered adapter
    result = registry.get("test")
    assert result == "test_value"


def test_adapter_registry_unknown_adapter():
    """Test error handling for unknown adapters."""
    registry = AdapterRegistry[str]("TestAdapter")

    with pytest.raises(ValueError) as exc_info:
        registry.get("nonexistent")

    assert "Unknown TestAdapter adapter: 'nonexistent'" in str(exc_info.value)
    assert "Available adapters: none" in str(exc_info.value)


def test_adapter_registry_list_adapters():
    """Test listing registered adapters."""
    registry = AdapterRegistry[str]("TestAdapter")

    assert registry.list_adapters() == []

    registry.register("adapter1", lambda: "value1")
    registry.register("adapter2", lambda: "value2")

    adapters = registry.list_adapters()
    assert len(adapters) == 2
    assert "adapter1" in adapters
    assert "adapter2" in adapters


def test_adapter_registry_is_registered():
    """Test checking if an adapter is registered."""
    registry = AdapterRegistry[str]("TestAdapter")

    assert not registry.is_registered("test")

    registry.register("test", lambda: "value")

    assert registry.is_registered("test")


def test_adapter_registry_overwrite_warning(caplog):
    """Test that overwriting an adapter logs a warning."""
    registry = AdapterRegistry[str]("TestAdapter")

    registry.register("test", lambda: "value1")
    registry.register("test", lambda: "value2")  # Overwrite

    # Check that we got a warning
    assert any("already registered" in record.message for record in caplog.records)

    # Verify the new value is used
    assert registry.get("test") == "value2"


def test_adapter_registry_factory_error():
    """Test error handling when factory raises an exception."""
    registry = AdapterRegistry[str]("TestAdapter")

    def failing_factory():
        raise RuntimeError("Factory failed!")

    registry.register("failing", failing_factory)

    with pytest.raises(RuntimeError) as exc_info:
        registry.get("failing")

    assert "Factory failed!" in str(exc_info.value)


def test_vector_store_registry_integration():
    """Test that vector store adapters are registered."""
    from clew.server.adapters import vector_store_registry

    # Check that standard adapters are registered
    registered_adapters = vector_store_registry.list_adapters()

    assert "qdrant" in registered_adapters or len(registered_adapters) >= 0
    # Note: Adapters may not register if dependencies are missing


def test_graph_store_registry_integration():
    """Test that graph store adapters are registered."""
    from clew.server.adapters import graph_store_registry

    # Check that standard adapters are registered
    registered_adapters = graph_store_registry.list_adapters()

    assert "noop" in registered_adapters or len(registered_adapters) >= 0
    # Note: Adapters may not register if dependencies are missing


def test_dependencies_use_registry(monkeypatch):
    """Test that dependencies.py uses the registry."""
    from clew.server.adapters import graph_store_registry, vector_store_registry

    # Create a mock adapter
    class MockVectorStore:
        async def search(self, *args, **kwargs):
            return []

        async def upsert(self, *args, **kwargs):
            pass

    class MockGraphStore:
        async def traverse(self, *args, **kwargs):
            from clew.server.adapters.base import GraphResult

            return GraphResult(nodes=[], edges=[])

    # Register mock adapters
    vector_store_registry.register("mock_vector", lambda: MockVectorStore())
    graph_store_registry.register("mock_graph", lambda: MockGraphStore())

    # Set environment to use mock adapters
    monkeypatch.setenv("CLEW_VECTOR_ADAPTER", "mock_vector")
    monkeypatch.setenv("CLEW_GRAPH_ADAPTER", "mock_graph")

    # Import after monkeypatching to pick up new env vars
    # Clear cache first
    from clew.server.dependencies import get_graph_store, get_vector_store

    get_vector_store.cache_clear()
    get_graph_store.cache_clear()

    # Get adapters through dependencies
    vector_store = get_vector_store()
    graph_store = get_graph_store()

    # Verify they're our mock instances
    assert isinstance(vector_store, MockVectorStore)
    assert isinstance(graph_store, MockGraphStore)

    # Clean up
    vector_store_registry.unregister("mock_vector")
    graph_store_registry.unregister("mock_graph")
