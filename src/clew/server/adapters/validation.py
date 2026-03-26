"""
Protocol Validation Utilities

Provides runtime validation to ensure adapter implementations
strictly adhere to their protocol contracts, enabling true
Liskov Substitution Principle compliance.
"""

import inspect
from typing import Any

from .base import EmbeddingProvider, GraphStore, VectorStore


class ProtocolValidationError(Exception):
    """Raised when an adapter implementation violates its protocol contract."""


def _non_self_params(sig: inspect.Signature) -> list[inspect.Parameter]:
    """Return signature parameters excluding 'self'."""
    return [p for p in sig.parameters.values() if p.name != "self"]


def _validate_signature(member_name: str, protocol_member: Any, impl_member: Any, strict: bool) -> str | None:
    """Check if implementation method signature matches protocol."""
    if not (inspect.isfunction(protocol_member) or inspect.ismethod(protocol_member)):
        return None
    try:
        proto_params = _non_self_params(inspect.signature(protocol_member))
        impl_params = _non_self_params(inspect.signature(impl_member))
        if strict and len(impl_params) < len(proto_params):
            return (
                f"Method {member_name}: implementation has fewer parameters "
                f"than protocol ({len(impl_params)} < {len(proto_params)})"
            )
    except (ValueError, TypeError):
        pass
    return None


def _get_protocol_members(protocol: type) -> dict[str, Any]:
    """Return public functions and properties defined by a protocol."""
    return {
        name: member
        for name, member in inspect.getmembers(protocol)
        if not name.startswith("_") and (inspect.isfunction(member) or isinstance(member, property))
    }


def _collect_violations(implementation: Any, protocol: type, strict: bool) -> list[str]:
    """Return a list of protocol violation descriptions (empty if compliant)."""
    errors: list[str] = []
    for name, proto_member in _get_protocol_members(protocol).items():
        if not hasattr(implementation, name):
            errors.append(f"Missing required method/property: {name}")
            continue
        if error := _validate_signature(name, proto_member, getattr(implementation, name), strict):
            errors.append(error)
    return errors


def validate_protocol_implementation(implementation: Any, protocol: type, strict: bool = True) -> None:
    """
    Validate that an implementation correctly implements a protocol.

    Raises:
        ProtocolValidationError: If the implementation violates the protocol
    """
    impl_name = implementation.__class__.__name__
    protocol_name = protocol.__name__

    if not isinstance(implementation, protocol):
        raise ProtocolValidationError(
            f"{impl_name} does not implement {protocol_name} protocol. "
            f"Missing required methods or incorrect signatures."
        )

    errors = _collect_violations(implementation, protocol, strict)
    if errors:
        raise ProtocolValidationError(f"{impl_name} violates {protocol_name} protocol:\n  - " + "\n  - ".join(errors))


# Convenience validators — thin wrappers kept for backward compatibility


def validate_vector_store(store: Any) -> None:
    """Validate a VectorStore implementation."""
    validate_protocol_implementation(store, VectorStore)


def validate_graph_store(store: Any) -> None:
    """Validate a GraphStore implementation."""
    validate_protocol_implementation(store, GraphStore)


def validate_embedding_provider(provider: Any) -> None:
    """Validate an EmbeddingProvider implementation."""
    validate_protocol_implementation(provider, EmbeddingProvider)


def get_protocol_compliance_report(implementation: Any, protocol: type) -> dict:
    """Generate a detailed compliance report without raising exceptions."""
    violations = _collect_violations(implementation, protocol, strict=True)
    missing = [v for v in violations if v.startswith("Missing")]
    mismatches = [v for v in violations if "parameters" in v.lower()]
    return {
        "compliant": isinstance(implementation, protocol) and not violations,
        "protocol": protocol.__name__,
        "implementation": implementation.__class__.__name__,
        "missing_methods": missing,
        "signature_mismatches": mismatches,
    }
