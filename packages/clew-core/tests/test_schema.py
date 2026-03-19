"""Tests for DCP Pydantic schemas (DomainNode, ConceptNode, PreceptNode)."""

from datetime import datetime

import pytest
from clewso_core.schema import ConceptNode, DomainNode, IntentNode, PreceptNode, StateNode, TacticNode
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# DomainNode
# ---------------------------------------------------------------------------


class TestDomainNode:
    def test_minimal_valid(self):
        node = DomainNode(id="domain_security", name="Security")
        assert node.id == "domain_security"
        assert node.name == "Security"
        assert node.description is None

    def test_with_description(self):
        node = DomainNode(id="domain_finops", name="FinOps", description="Financial operations")
        assert node.description == "Financial operations"

    def test_serialization_roundtrip(self):
        node = DomainNode(id="domain_security", name="Security", description="Sec rules")
        data = node.model_dump()
        restored = DomainNode.model_validate(data)
        assert restored == node

    def test_empty_id_raises(self):
        with pytest.raises(ValidationError):
            DomainNode(id="", name="Security")

    def test_empty_name_raises(self):
        with pytest.raises(ValidationError):
            DomainNode(id="domain_security", name="")

    def test_id_too_long_raises(self):
        with pytest.raises(ValidationError):
            DomainNode(id="x" * 257, name="Security")

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            DomainNode(id="domain_security", name="x" * 257)


# ---------------------------------------------------------------------------
# ConceptNode
# ---------------------------------------------------------------------------


class TestConceptNode:
    def test_minimal_valid(self):
        node = ConceptNode(id="concept_pii", name="PII", domain_id="domain_security")
        assert node.id == "concept_pii"
        assert node.name == "PII"
        assert node.domain_id == "domain_security"

    def test_serialization_roundtrip(self):
        node = ConceptNode(id="concept_hotfix", name="Hotfix", domain_id="domain_eng")
        data = node.model_dump()
        restored = ConceptNode.model_validate(data)
        assert restored == node

    def test_empty_id_raises(self):
        with pytest.raises(ValidationError):
            ConceptNode(id="", name="PII", domain_id="domain_security")

    def test_empty_domain_id_raises(self):
        with pytest.raises(ValidationError):
            ConceptNode(id="concept_pii", name="PII", domain_id="")

    def test_missing_domain_id_raises(self):
        with pytest.raises(ValidationError):
            ConceptNode(id="concept_pii", name="PII")


# ---------------------------------------------------------------------------
# PreceptNode
# ---------------------------------------------------------------------------


_VALID_PRECEPT_KWARGS = dict(
    id="precept_001",
    description="Developers MUST sign all commits.",
    source_system="local_config",
    author="alice@example.com",
    classification="MUST",
    operational_constraint="block",
    is_normative=True,
)


class TestPreceptNode:
    def test_minimal_valid(self):
        node = PreceptNode(**_VALID_PRECEPT_KWARGS)
        assert node.id == "precept_001"
        assert node.classification == "MUST"
        assert node.operational_constraint == "block"
        assert node.is_normative is True
        assert isinstance(node.timestamp, datetime)

    def test_timestamp_default(self):
        node = PreceptNode(**_VALID_PRECEPT_KWARGS)
        assert node.timestamp is not None

    def test_explicit_timestamp(self):
        ts = datetime(2025, 1, 15, 12, 0, 0)
        node = PreceptNode(**{**_VALID_PRECEPT_KWARGS, "timestamp": ts})
        assert node.timestamp == ts

    @pytest.mark.parametrize("classification", ["MUST", "MUST_NOT", "SHOULD", "SHOULD_NOT", "MAY"])
    def test_valid_classifications(self, classification: str):
        node = PreceptNode(**{**_VALID_PRECEPT_KWARGS, "classification": classification})
        assert node.classification == classification

    def test_invalid_classification_raises(self):
        with pytest.raises(ValidationError):
            PreceptNode(**{**_VALID_PRECEPT_KWARGS, "classification": "MUST_HAVE"})

    @pytest.mark.parametrize("constraint", ["block", "require", "allow", "bypass", "warn"])
    def test_valid_operational_constraints(self, constraint: str):
        node = PreceptNode(**{**_VALID_PRECEPT_KWARGS, "operational_constraint": constraint})
        assert node.operational_constraint == constraint

    def test_invalid_operational_constraint_raises(self):
        with pytest.raises(ValidationError):
            PreceptNode(**{**_VALID_PRECEPT_KWARGS, "operational_constraint": "deny"})

    def test_serialization_roundtrip(self):
        node = PreceptNode(**_VALID_PRECEPT_KWARGS)
        data = node.model_dump()
        restored = PreceptNode.model_validate(data)
        assert restored == node

    def test_empty_id_raises(self):
        with pytest.raises(ValidationError):
            PreceptNode(**{**_VALID_PRECEPT_KWARGS, "id": ""})

    def test_empty_description_raises(self):
        with pytest.raises(ValidationError):
            PreceptNode(**{**_VALID_PRECEPT_KWARGS, "description": ""})

    def test_empty_author_raises(self):
        with pytest.raises(ValidationError):
            PreceptNode(**{**_VALID_PRECEPT_KWARGS, "author": ""})

    def test_is_normative_false(self):
        node = PreceptNode(**{**_VALID_PRECEPT_KWARGS, "is_normative": False})
        assert node.is_normative is False

    def test_json_serialization(self):
        node = PreceptNode(**_VALID_PRECEPT_KWARGS)
        json_str = node.model_dump_json()
        restored = PreceptNode.model_validate_json(json_str)
        assert restored == node


# ---------------------------------------------------------------------------
# StateNode
# ---------------------------------------------------------------------------


class TestStateNode:
    def test_minimal_valid(self):
        node = StateNode(id="state_01", name="Sanitized", cfg_condition="is_sanitized == True")
        assert node.id == "state_01"
        assert node.name == "Sanitized"
        assert node.cfg_condition == "is_sanitized == True"

    def test_empty_id_raises(self):
        with pytest.raises(ValidationError):
            StateNode(id="", name="Sanitized", cfg_condition="true")

    def test_empty_cfg_condition_raises(self):
        with pytest.raises(ValidationError):
            StateNode(id="state_01", name="Sanitized", cfg_condition="")


# ---------------------------------------------------------------------------
# IntentNode
# ---------------------------------------------------------------------------


class TestIntentNode:
    def test_minimal_valid(self):
        node = IntentNode(id="intent_opt", category="Opt")
        assert node.id == "intent_opt"
        assert node.category == "Opt"

    def test_invalid_category_raises(self):
        with pytest.raises(ValidationError):
            IntentNode(id="intent_01", category="Unknown")


# ---------------------------------------------------------------------------
# TacticNode
# ---------------------------------------------------------------------------


class TestTacticNode:
    def test_minimal_valid(self):
        node = TacticNode(id="hash_8x8", function_name="hashlib.sha256", file_path="utils/crypto.py")
        assert node.id == "hash_8x8"
        assert node.function_name == "hashlib.sha256"
        assert node.file_path == "utils/crypto.py"

    def test_empty_function_name_raises(self):
        with pytest.raises(ValidationError):
            TacticNode(id="hash_8x8", function_name="", file_path="utils/crypto.py")
