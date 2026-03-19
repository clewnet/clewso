import sys
import unittest
from unittest.mock import MagicMock

# Mock tree_sitter and tree_sitter_language_pack before importing src.parser
sys.modules["tree_sitter"] = MagicMock()
sys.modules["tree_sitter_language_pack"] = MagicMock()

# Now import CodeParser and extracted functions
from clewso_ingestion.parser import (  # noqa: E402
    CodeParser,
)


class MockNode:
    def __init__(self, type_val, text=None, children=None, fields=None):
        self.type = type_val
        self.text = text.encode("utf-8") if text else b""
        self.children = children or []
        self.fields = fields or {}

    def child_by_field_name(self, name):
        return self.fields.get(name)

    @property
    def child_count(self):
        return len(self.children)


class TestCodeParserGetName(unittest.TestCase):
    def setUp(self):
        self.parser = CodeParser()

    def test_get_name_generic_identifier(self):
        """Test retrieving name from a direct 'identifier' child."""
        child = MockNode("identifier", text="MyFunction")
        node = MockNode("function_definition", children=[child])

        name = CodeParser._extract_name(node, "python")
        self.assertEqual(name, "MyFunction")

    def test_get_name_generic_type_identifier(self):
        """Test retrieving name from a direct 'type_identifier' child (e.g. C++ class)."""
        child = MockNode("type_identifier", text="MyClass")
        node = MockNode("class_specifier", children=[child])

        name = CodeParser._extract_name(node, "cpp")
        self.assertEqual(name, "MyClass")

    def test_get_name_python_field_name(self):
        """Test retrieving name from 'name' field in Python function definitions."""
        name_node = MockNode("identifier", text="my_func_field")
        node = MockNode("function_definition", fields={"name": name_node})

        name = CodeParser._extract_name(node, "python")
        self.assertEqual(name, "my_func_field")

    def test_get_name_cpp_declarator_simple(self):
        """Test retrieving name from C++ declarator structure."""
        # node -> declarator (function_declarator) -> declarator (identifier)
        identifier = MockNode("identifier", text="cpp_func")
        func_decl = MockNode("function_declarator", fields={"declarator": identifier})
        node = MockNode("function_definition", fields={"declarator": func_decl})

        name = CodeParser._extract_name(node, "cpp")
        self.assertEqual(name, "cpp_func")

    def test_get_name_cpp_declarator_complex(self):
        """Test retrieving name from complex C++ declarator (pointer/reference)."""
        # node -> declarator (pointer) -> declarator (func) -> declarator (identifier)
        identifier = MockNode("identifier", text="complex_cpp_func")
        func_decl = MockNode("function_declarator", fields={"declarator": identifier})
        pointer_decl = MockNode("pointer_declarator", fields={"declarator": func_decl})
        node = MockNode("function_definition", fields={"declarator": pointer_decl})

        name = CodeParser._extract_name(node, "cpp")
        self.assertEqual(name, "complex_cpp_func")

    def test_get_name_fallback_none(self):
        """Test fallback when no name is found."""
        node = MockNode("unknown_block")
        name = CodeParser._extract_name(node, "python")
        self.assertIsNone(name)

    def test_get_name_python_name_child_type(self):
        """Test retrieving name when a child has type 'name'."""
        child = MockNode("name", text="SpecialName")
        node = MockNode("special_node", children=[child])

        name = CodeParser._extract_name(node, "python")
        self.assertEqual(name, "SpecialName")

    def test_get_name_cpp_fallback_child(self):
        """Test C++ fallback: identifier child in unexpected declarator."""
        # declarator -> unexpected_node -> identifier
        identifier = MockNode("identifier", text="fallback_cpp_func")
        unexpected = MockNode("unexpected_node", children=[identifier])
        node = MockNode("function_definition", fields={"declarator": unexpected})

        name = CodeParser._extract_name(node, "cpp")
        self.assertEqual(name, "fallback_cpp_func")

    def test_get_name_cpp_fallback_text(self):
        """Test C++ fallback: text of leaf node if no identifier found."""
        # declarator -> leaf_node (no children, just text)
        leaf = MockNode("leaf_node", text="leaf_name")
        node = MockNode("function_definition", fields={"declarator": leaf})

        name = CodeParser._extract_name(node, "cpp")
        self.assertEqual(name, "leaf_name")


def test_lazy_loading_caches_failure():
    """
    Test that CodeParser caches language loading failures so repeated
    parse_file calls for the same language don't retry endlessly.
    """
    mock_get_parser = sys.modules["tree_sitter_language_pack"].get_parser
    mock_get_parser.side_effect = Exception("Simulated failure")

    parser = CodeParser()

    # First call should attempt loading and fail gracefully
    result = parser.parse_file("test.rs", b"fn main() {}")
    assert result == []
    assert "rust" in parser.parsers
    assert parser.parsers["rust"] is None

    # Second call should use the cached None without calling get_parser again
    call_count_before = mock_get_parser.call_count
    result = parser.parse_file("test.rs", b"fn main() {}")
    assert result == []
    assert mock_get_parser.call_count == call_count_before


def test_extension_mapping():
    """
    Test that _get_lang_from_ext uses the registry-based extension map.
    """
    CodeParser()
    assert CodeParser._lang_for("main.py") == "python"
    assert CodeParser._lang_for("lib.rs") == "rust"
    assert CodeParser._lang_for("App.tsx") == "typescript"
    assert CodeParser._lang_for("main.go") == "go"
    assert CodeParser._lang_for("Main.java") == "java"
    assert CodeParser._lang_for("style.css") == "css"
    assert CodeParser._lang_for("unknown.xyz") is None
