"""
Adapter Registry System

Implements the Registry pattern for dynamic adapter registration.
This eliminates hardcoded if/else chains in dependency injection
and follows the Open/Closed Principle.

Includes optional protocol validation to ensure registered adapters
strictly adhere to their protocol contracts (Liskov Substitution).

Usage:
    # Register an adapter
    vector_store_registry.register(
        "qdrant",
        lambda: QdrantStore(host="localhost", port=6333)
    )

    # Get an adapter by name
    store = vector_store_registry.get("qdrant")
"""

import logging
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

# Generic type for adapters
T = TypeVar("T")


class AdapterRegistry(Generic[T]):
    """
    Generic registry for adapters.

    Supports:
    - Dynamic registration by name
    - Factory functions for lazy initialization
    - Thread-safe registration and lookup
    - Optional protocol validation (Liskov Substitution)
    - Helpful error messages

    Type parameter T should be a Protocol (e.g., VectorStore, GraphStore).
    """

    def __init__(self, adapter_type_name: str, protocol: type | None = None, validate: bool = False):
        """
        Initialize the registry.

        Args:
            adapter_type_name: Human-readable name for error messages (e.g., "VectorStore")
            protocol: Optional protocol class for validation
            validate: If True, validate adapters against protocol on get()
        """
        self.adapter_type_name = adapter_type_name
        self.protocol = protocol
        self.validate = validate
        self._factories: dict[str, Callable[[], T]] = {}
        self._lock = Lock()
        logger.debug(f"Initialized {adapter_type_name} registry (validation={'on' if validate else 'off'})")

    def register(self, name: str, factory: Callable[[], T]) -> None:
        """
        Register an adapter with a factory function.

        Args:
            name: Unique identifier for this adapter (e.g., "qdrant", "pgvector")
            factory: Callable that returns an instance of the adapter

        Example:
            registry.register("qdrant", lambda: QdrantStore(host="localhost"))
        """
        with self._lock:
            if name in self._factories:
                logger.warning(f"{self.adapter_type_name} '{name}' is already registered. Overwriting.")
            self._factories[name] = factory
            logger.debug(f"Registered {self.adapter_type_name}: {name}")

    def get(self, name: str) -> T:
        """
        Get an adapter instance by name.

        Args:
            name: The adapter name to retrieve

        Returns:
            An instance of the adapter

        Raises:
            ValueError: If the adapter name is not registered
            ProtocolValidationError: If validation is enabled and adapter doesn't comply
        """
        with self._lock:
            factory = self._factories.get(name)

            if factory is None:
                available = ", ".join(self._factories.keys()) or "none"
                raise ValueError(
                    f"Unknown {self.adapter_type_name} adapter: '{name}'. "
                    f"Available adapters: {available}. "
                    f"Did you forget to import the adapter module?"
                )

            try:
                instance = factory()

                # Optional protocol validation
                if self.validate and self.protocol:
                    from .validation import validate_protocol_implementation

                    validate_protocol_implementation(instance, self.protocol)
                    logger.debug(f"Protocol validation passed for {name}")

                return instance
            except Exception as e:
                logger.error(
                    f"Failed to initialize {self.adapter_type_name} '{name}': {e}",
                    exc_info=True,
                )
                raise

    def is_registered(self, name: str) -> bool:
        """Check if an adapter is registered."""
        with self._lock:
            return name in self._factories

    def list_adapters(self) -> list[str]:
        """Get a list of all registered adapter names."""
        with self._lock:
            return list(self._factories.keys())

    def unregister(self, name: str) -> None:
        """
        Remove an adapter from the registry.

        Mainly useful for testing.

        Args:
            name: The adapter name to remove
        """
        with self._lock:
            if name in self._factories:
                del self._factories[name]
                logger.debug(f"Unregistered {self.adapter_type_name}: {name}")


# =============================================================================
# Global Registry Instances
# =============================================================================

# Import here to avoid circular imports
from .base import EmbeddingProvider, GraphStore, VectorStore  # noqa: E402

# Create singleton registry instances
vector_store_registry = AdapterRegistry[VectorStore]("VectorStore")
graph_store_registry = AdapterRegistry[GraphStore]("GraphStore")
embedding_provider_registry = AdapterRegistry[EmbeddingProvider]("EmbeddingProvider")
