"""
Language Registry

Data-driven configuration for tree-sitter language support.
Each LanguageConfig maps file extensions to a tree-sitter grammar and declares
the AST node types used for extracting definitions, imports, and calls.

To add a new language, add a LanguageConfig entry to LANGUAGE_CONFIGS — no other
code changes required.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageConfig:
    """Configuration for a single tree-sitter language grammar."""

    name: str
    extensions: tuple[str, ...]
    definition_types: frozenset[str] = field(default_factory=frozenset)
    import_types: frozenset[str] = field(default_factory=frozenset)
    call_types: frozenset[str] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Language configurations
# ---------------------------------------------------------------------------

LANGUAGE_CONFIGS: dict[str, LanguageConfig] = {}


def _register(*configs: LanguageConfig) -> None:
    for cfg in configs:
        LANGUAGE_CONFIGS[cfg.name] = cfg


_register(
    # ── Existing languages (full extraction) ──────────────────────────────
    LanguageConfig(
        name="python",
        extensions=(".py",),
        definition_types=frozenset({"function_definition", "class_definition"}),
        import_types=frozenset({"import_statement", "import_from_statement"}),
        call_types=frozenset({"call"}),
    ),
    LanguageConfig(
        name="javascript",
        extensions=(".js", ".jsx"),
        definition_types=frozenset({"function_declaration", "class_declaration", "method_definition"}),
        import_types=frozenset({"import_statement"}),
        call_types=frozenset({"call_expression"}),
    ),
    LanguageConfig(
        name="typescript",
        extensions=(".ts", ".tsx"),
        definition_types=frozenset({"function_declaration", "class_declaration", "method_definition"}),
        import_types=frozenset({"import_statement"}),
        call_types=frozenset({"call_expression"}),
    ),
    LanguageConfig(
        name="go",
        extensions=(".go",),
        definition_types=frozenset({"function_declaration", "method_declaration", "type_declaration"}),
        import_types=frozenset({"import_declaration", "import_spec"}),
        call_types=frozenset({"call_expression"}),
    ),
    LanguageConfig(
        name="rust",
        extensions=(".rs",),
        definition_types=frozenset(
            {
                "function_item",
                "struct_item",
                "enum_item",
                "trait_item",
                "impl_item",
                "type_item",
            }
        ),
        import_types=frozenset({"use_declaration"}),
        call_types=frozenset({"call_expression", "macro_invocation"}),
    ),
    LanguageConfig(
        name="cpp",
        extensions=(".cpp", ".cc", ".c", ".h", ".hpp"),
        definition_types=frozenset(
            {
                "function_definition",
                "class_specifier",
                "struct_specifier",
                "namespace_definition",
            }
        ),
        import_types=frozenset({"preproc_include"}),
        call_types=frozenset({"call_expression"}),
    ),
    # ── New languages ─────────────────────────────────────────────────────
    LanguageConfig(
        name="java",
        extensions=(".java",),
        definition_types=frozenset(
            {
                "method_declaration",
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
            }
        ),
        import_types=frozenset({"import_declaration"}),
        call_types=frozenset({"method_invocation"}),
    ),
    LanguageConfig(
        name="c_sharp",
        extensions=(".cs",),
        definition_types=frozenset(
            {
                "method_declaration",
                "class_declaration",
                "interface_declaration",
                "struct_declaration",
                "enum_declaration",
            }
        ),
        import_types=frozenset({"using_directive"}),
        call_types=frozenset({"invocation_expression"}),
    ),
    LanguageConfig(
        name="ruby",
        extensions=(".rb",),
        definition_types=frozenset({"method", "class", "module", "singleton_method"}),
        import_types=frozenset({"call"}),  # require/require_relative are calls in Ruby
        call_types=frozenset({"call", "method_call"}),
    ),
    LanguageConfig(
        name="php",
        extensions=(".php",),
        definition_types=frozenset({"function_definition", "class_declaration", "method_declaration"}),
        import_types=frozenset({"namespace_use_declaration"}),
        call_types=frozenset({"function_call_expression", "member_call_expression"}),
    ),
    LanguageConfig(
        name="swift",
        extensions=(".swift",),
        definition_types=frozenset(
            {
                "function_declaration",
                "class_declaration",
                "struct_declaration",
                "protocol_declaration",
                "enum_declaration",
            }
        ),
        import_types=frozenset({"import_declaration"}),
        call_types=frozenset({"call_expression"}),
    ),
    LanguageConfig(
        name="kotlin",
        extensions=(".kt", ".kts"),
        definition_types=frozenset({"function_declaration", "class_declaration", "object_declaration"}),
        import_types=frozenset({"import_header"}),
        call_types=frozenset({"call_expression"}),
    ),
    LanguageConfig(
        name="scala",
        extensions=(".scala",),
        definition_types=frozenset(
            {"function_definition", "class_definition", "object_definition", "trait_definition"}
        ),
        import_types=frozenset({"import_declaration"}),
        call_types=frozenset({"call_expression"}),
    ),
    LanguageConfig(
        name="lua",
        extensions=(".lua",),
        definition_types=frozenset({"function_declaration", "function_definition_statement"}),
        call_types=frozenset({"function_call"}),
    ),
    LanguageConfig(
        name="elixir",
        extensions=(".ex", ".exs"),
        definition_types=frozenset({"call"}),  # def/defmodule are calls in Elixir's grammar
    ),
    LanguageConfig(
        name="haskell",
        extensions=(".hs",),
        definition_types=frozenset({"function", "type_alias", "newtype", "adt"}),
        import_types=frozenset({"import"}),
    ),
    LanguageConfig(
        name="ocaml",
        extensions=(".ml", ".mli"),
        definition_types=frozenset({"let_binding", "type_binding", "module_binding"}),
    ),
    LanguageConfig(
        name="bash",
        extensions=(".sh", ".bash"),
        definition_types=frozenset({"function_definition"}),
        call_types=frozenset({"command"}),
    ),
    LanguageConfig(
        name="html",
        extensions=(".html", ".htm"),
        definition_types=frozenset(),
    ),
    LanguageConfig(
        name="css",
        extensions=(".css",),
        definition_types=frozenset(),
    ),
    LanguageConfig(
        name="yaml",
        extensions=(".yaml", ".yml"),
        definition_types=frozenset(),
    ),
    LanguageConfig(
        name="toml",
        extensions=(".toml",),
        definition_types=frozenset(),
    ),
    LanguageConfig(
        name="json",
        extensions=(".json",),
        definition_types=frozenset(),
    ),
    LanguageConfig(
        name="sql",
        extensions=(".sql",),
        definition_types=frozenset(),
    ),
    LanguageConfig(
        name="zig",
        extensions=(".zig",),
        definition_types=frozenset({"function_declaration"}),
        call_types=frozenset({"call_expression"}),
    ),
    LanguageConfig(
        name="dart",
        extensions=(".dart",),
        definition_types=frozenset({"function_signature", "class_definition", "method_signature"}),
        import_types=frozenset({"import_or_export"}),
        call_types=frozenset({"call_expression"}),
    ),
)


# ---------------------------------------------------------------------------
# Derived lookup tables
# ---------------------------------------------------------------------------


def build_extension_map() -> dict[str, str]:
    """Build a flat mapping from file extension to tree-sitter language name.

    Returns:
        dict mapping e.g. ".py" → "python", ".rs" → "rust"
    """
    ext_map: dict[str, str] = {}
    for cfg in LANGUAGE_CONFIGS.values():
        for ext in cfg.extensions:
            ext_map[ext] = cfg.name
    return ext_map


# Pre-built for fast import-time access
EXTENSION_MAP: dict[str, str] = build_extension_map()
