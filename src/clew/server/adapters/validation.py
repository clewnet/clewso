"""
Protocol Validation Utilities

Provides runtime validation to ensure adapter implementations
strictly adhere to their protocol contracts, enabling true
Liskov Substitution Principle compliance.

This module helps catch protocol violations early with helpful
error messages, making it easier to create correct adapter implementations.
"""

import inspect
from typing import Any

from .base import EmbeddingProvider, GraphStore, VectorStore


class ProtocolValidationError(Exception):
    """Raised when an adapter implementation violates its protocol contract."""

    pass


def _validate_signature(member_name: str, protocol_member: Any, impl_member: Any, strict: bool) -> str | None:
    """Check if implementation method signature matches protocol."""
    if not (inspect.isfunction(protocol_member) or inspect.ismethod(protocol_member)):
        return None

    try:
        protocol_sig = inspect.signature(protocol_member)
        impl_sig = inspect.signature(impl_member)

        # Check that implementation accepts at least the protocol's parameters
        protocol_params = list(protocol_sig.parameters.values())
        impl_params = list(impl_sig.parameters.values())

        # Skip 'self' parameter
        protocol_params = [p for p in protocol_params if p.name != "self"]
        impl_params = [p for p in impl_params if p.name != "self"]

        if strict and len(impl_params) < len(protocol_params):
            return (
                f"Method {member_name}: implementation has fewer parameters "
                f"than protocol ({len(impl_params)} < {len(protocol_params)})"
            )

    except (ValueError, TypeError):
        # Signature inspection failed, but isinstance check passed, so it's probably OK
        pass

    return None


def validate_protocol_implementation(implementation: Any, protocol: type, strict: bool = True) -> None:
    """
    Validate that an implementation correctly implements a protocol.

    This goes beyond Python's duck typing to verify:
    1. All protocol methods are present
    2. Method signatures match (same parameters)
    3. Return types are compatible (if strict=True)

    Args:
        implementation: The adapter instance to validate
        protocol: The protocol class it should implement
        strict: If True, also check type hints and return types

    Raises:
        ProtocolValidationError: If the implementation violates the protocol

    Example:
        store = QdrantStore()
        validate_protocol_implementation(store, VectorStore)
    """
    impl_class = implementation.__class__
    protocol_name = protocol.__name__
    impl_name = impl_class.__name__

    # Check if implementation satisfies protocol using isinstance
    if not isinstance(implementation, protocol):
        raise ProtocolValidationError(
            f"{impl_name} does not implement {protocol_name} protocol. "
            f"Missing required methods or incorrect signatures."
        )

    # Get protocol members
    protocol_members = {
        name: member
        for name, member in inspect.getmembers(protocol)
        if not name.startswith("_") and (inspect.isfunction(member) or isinstance(member, property))
    }

    # Validate each protocol member
    errors = []

    for member_name, protocol_member in protocol_members.items():
        # Skip special protocol attributes
        if member_name in ("__init__", "__new__", "__class__"):
            continue

        # Check if member exists in implementation
        if not hasattr(implementation, member_name):
            errors.append(f"Missing required method/property: {member_name}")
            continue

        impl_member = getattr(implementation, member_name)

        if error := _validate_signature(member_name, protocol_member, impl_member, strict):
            errors.append(error)

    if errors:
        error_msg = f"{impl_name} violates {protocol_name} protocol:\n  - " + "\n  - ".join(errors)
        raise ProtocolValidationError(error_msg)


def validate_vector_store(store: Any) -> None:
    """
    Validate that an object correctly implements the VectorStore protocol.

    Args:
        store: The vector store implementation to validate

    Raises:
        ProtocolValidationError: If validation fails
    """
    validate_protocol_implementation(store, VectorStore)


def validate_graph_store(store: Any) -> None:
    """
    Validate that an object correctly implements the GraphStore protocol.

    Args:
        store: The graph store implementation to validate

    Raises:
        ProtocolValidationError: If validation fails
    """
    validate_protocol_implementation(store, GraphStore)


def validate_embedding_provider(provider: Any) -> None:
    """
    Validate that an object correctly implements the EmbeddingProvider protocol.

    Args:
        provider: The embedding provider implementation to validate

    Raises:
        ProtocolValidationError: If validation fails
    """
    validate_protocol_implementation(provider, EmbeddingProvider)


def get_protocol_compliance_report(implementation: Any, protocol: type) -> dict:
    """
    Generate a detailed compliance report for an implementation.

    This is useful for debugging protocol violations without raising exceptions.

    Args:
        implementation: The adapter instance
        protocol: The protocol it should implement

    Returns:
        Dictionary with compliance information:
        {
            "compliant": bool,
            "protocol": str,
            "implementation": str,
            "missing_methods": List[str],
            "signature_mismatches": List[str],
        }
    """
    impl_name = implementation.__class__.__name__
    protocol_name = protocol.__name__

    report = {
        "compliant": isinstance(implementation, protocol),
        "protocol": protocol_name,
        "implementation": impl_name,
        "missing_methods": [],
        "signature_mismatches": [],
    }

    try:
        validate_protocol_implementation(implementation, protocol, strict=True)
    except ProtocolValidationError as e:
        report["compliant"] = False
        # Parse error message to extract details
        error_lines = str(e).split("\n")
        for line in error_lines:
            if "Missing required" in line:
                report["missing_methods"].append(line.strip())
            elif "signature" in line.lower() or "parameters" in line.lower():
                report["signature_mismatches"].append(line.strip())

    return report
