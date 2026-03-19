"""
DCP (Domain-Concept-Precept) Pydantic Schemas

Defines the three core graph node types used to model governance rules:
  - DomainNode     — spatial boundary for a rule set
  - ConceptNode    — abstract entity or workflow being governed
  - PreceptNode    — atomic rule or constraint (RFC-2119 classified)
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class DomainNode(BaseModel):
    """The spatial boundary for a rule."""

    id: str = Field(..., min_length=1, max_length=256, description="Unique deterministic ID (e.g., domain_security)")
    name: str = Field(..., min_length=1, max_length=256, description="Human readable name (e.g., Security, FinOps)")
    description: str | None = Field(default=None, max_length=2048)


class ConceptNode(BaseModel):
    """The abstract entity or workflow being governed."""

    id: str = Field(..., min_length=1, max_length=256, description="Unique deterministic ID (e.g., concept_pii)")
    name: str = Field(
        ..., min_length=1, max_length=256, description="Name of the concept (e.g., PII, Hotfix, UserAuth)"
    )
    domain_id: str = Field(..., min_length=1, max_length=256, description="The Domain this concept belongs to")


class PreceptNode(BaseModel):
    """The atomic rule or constraint."""

    id: str = Field(..., min_length=1, max_length=256, description="Unique deterministic ID")
    description: str = Field(..., min_length=1, max_length=4096, description="The actual text of the rule")
    source_system: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="e.g., 'local_config', 'jira_webhook', 'notion_api'",
    )
    author: str = Field(
        ..., min_length=1, max_length=512, description="Email/ID of the person or agent who authored the rule"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Governance Metadata
    classification: Literal["MUST", "MUST_NOT", "SHOULD", "SHOULD_NOT", "MAY"] = Field(
        ..., description="RFC-2119 compliance level for exact Graph constraint weighting"
    )
    operational_constraint: Literal["block", "require", "allow", "bypass", "warn"] = Field(
        ..., description="Operational enforcement action for this precept"
    )
    is_normative: bool = Field(
        ..., description="True if manually defined/immutable, False if emergent from integrations"
    )


class StateNode(BaseModel):
    """Runtime realities or Control Flow Graph (CFG) truths."""

    id: str = Field(..., min_length=1, max_length=256, description="Unique deterministic hash")
    name: str = Field(..., min_length=1, max_length=256, description="State identifier (e.g., 'Sanitized')")
    cfg_condition: str = Field(..., min_length=1, max_length=2048, description="The CFG reality (e.g., 'c->auth == 1')")


class IntentNode(BaseModel):
    """The high-level semantic 'Why' behind a code block."""

    id: str = Field(..., min_length=1, max_length=256, description="Unique deterministic ID")
    category: Literal["Security", "Opt", "Diag", "Governance", "Other"] = Field(
        ..., description="The broad category of the intent"
    )


class PolicyRule(BaseModel):
    """An enforceable policy rule for hook-based governance.

    Connected to a PreceptNode via [:ENFORCES] and optionally scoped
    to a DomainNode via [:SCOPED_TO].  See ADR-012 for architecture.
    """

    id: str = Field(
        ..., min_length=1, max_length=256, description="Unique deterministic ID (e.g., policy_no_unauthed_db)"
    )
    type: Literal["banned_import", "unguarded_path", "protected_write"] = Field(
        ..., description="Violation detection strategy"
    )
    pattern: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Type-specific match pattern: module glob, Cypher pattern, or file path glob",
    )
    severity: Literal["block", "warn", "audit"] = Field(
        ..., description="Enforcement action when the policy is violated"
    )
    message: str = Field(
        ..., min_length=1, max_length=2048, description="Human-readable violation message fed back to the agent"
    )
    precept_id: str | None = Field(default=None, max_length=256, description="FK to the PreceptNode this rule enforces")


class TacticNode(BaseModel):
    """The physical code execution or AST structure."""

    id: str = Field(..., min_length=1, max_length=256, description="Unique AST hash")
    function_name: str = Field(..., min_length=1, max_length=512, description="Name of the function or method")
    file_path: str = Field(..., min_length=1, max_length=1024, description="Path to the file containing the tactic")
