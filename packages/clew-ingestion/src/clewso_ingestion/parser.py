import logging
import os
from collections.abc import Callable
from typing import Any, cast

from tree_sitter import Node

from .pipeline.language_registry import EXTENSION_MAP, LANGUAGE_CONFIGS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node text helpers
# ---------------------------------------------------------------------------


def _node_text(node: Node | None) -> str | None:
    """Decode node text to str, or None if absent."""
    if node is not None and node.text:
        return node.text.decode("utf-8")
    return None


def _field_text(node: Node, field: str) -> str | None:
    """Extract decoded text from a named field child."""
    return _node_text(node.child_by_field_name(field))


def _first_child_text(node: Node, types: tuple[str, ...]) -> str | None:
    """Return text of the first child whose type is in *types*."""
    for child in node.children:
        if child.type in types and child.text:
            return child.text.decode("utf-8")
    return None


# ---------------------------------------------------------------------------
# Name extraction per language
# ---------------------------------------------------------------------------


def _get_name_python(node: Node) -> str | None:
    return _field_text(node, "name")


def _get_name_cpp(node: Node) -> str | None:
    declarator = node.child_by_field_name("declarator")
    if declarator:
        curr: Node | None = declarator
        while curr:
            if curr.type == "identifier":
                return _node_text(curr)
            if curr.type in ("function_declarator", "reference_declarator", "pointer_declarator"):
                curr = curr.child_by_field_name("declarator")
            else:
                ident = _first_child_text(curr, ("identifier",))
                if ident:
                    return ident
                if curr.child_count == 0:
                    return _node_text(curr)
                break
    return _field_text(node, "name")


_NAME_OVERRIDES: dict[str, Callable[[Node], str | None]] = {
    "python": _get_name_python,
    "cpp": _get_name_cpp,
}


# ---------------------------------------------------------------------------
# Import name extraction per language
# ---------------------------------------------------------------------------


def _get_import_python(node: Node) -> str | None:
    if node.type == "import_statement":
        for child in node.children:
            if child.type == "dotted_name":
                return _node_text(child)
            if child.type == "aliased_import":
                return _field_text(child, "name")
    elif node.type == "import_from_statement":
        module = _field_text(node, "module_name")
        if module:
            return module
        for child in node.children:
            if child.type == "relative_import":
                return _node_text(child)
    return None


def _get_import_go(node: Node) -> str | None:
    if node.type == "import_spec":
        text = _field_text(node, "path")
        return text.strip('"') if text else None
    return None


def _get_import_js(node: Node) -> str | None:
    if node.type == "import_statement":
        text = _field_text(node, "source")
        return text.strip("'\"") if text else None
    return None


def _get_import_cpp(node: Node) -> str | None:
    text = _field_text(node, "path")
    return text.strip('"<>') if text else None


def _get_import_generic(node: Node) -> str | None:
    for field in ("name", "path", "source", "module_name"):
        text = _field_text(node, field)
        if text:
            return text.strip('"<>')

    ident = _first_child_text(node, ("identifier", "scoped_identifier", "dotted_name", "string", "use_list"))
    return ident.strip('"<>') if ident else None


_IMPORT_HANDLERS: dict[str, Callable[[Node], str | None]] = {
    "python": _get_import_python,
    "go": _get_import_go,
    "javascript": _get_import_js,
    "typescript": _get_import_js,
    "cpp": _get_import_cpp,
}


# ---------------------------------------------------------------------------
# Call name extraction
# ---------------------------------------------------------------------------


def _get_call_name(node: Node) -> str | None:
    for field in ("function", "method", "name"):
        text = _field_text(node, field)
        if text:
            return text
    return None


# ---------------------------------------------------------------------------
# CodeParser
# ---------------------------------------------------------------------------


class CodeParser:
    """Tree-sitter based code parser with lazy language loading."""

    def __init__(self) -> None:
        self._parsers: dict[str, object | None] = {}

    def parse_file(self, file_path: str, content: bytes) -> list[dict]:
        lang = self._lang_for(file_path)
        if lang is None:
            return []

        parser = self._get_or_load_parser(lang)
        if parser is None:
            return []

        tree = cast(Any, parser).parse(content)
        results: list[dict] = []
        self._traverse(tree.root_node, results, lang)
        return results

    # -- lazy loading ------------------------------------------------------

    def _get_or_load_parser(self, lang_name: str) -> object | None:
        if lang_name in self._parsers:
            return self._parsers[lang_name]
        try:
            from tree_sitter_language_pack import get_parser  # type: ignore

            parser = get_parser(cast(Any, lang_name))
            self._parsers[lang_name] = parser
            return parser
        except Exception as e:
            logger.warning("Could not load language %s: %s", lang_name, e)
            self._parsers[lang_name] = None
            return None

    # -- traversal ---------------------------------------------------------

    def _traverse(self, node: Node, results: list[dict], lang: str) -> None:
        config = LANGUAGE_CONFIGS.get(lang)
        if config is None:
            return

        entry = self._classify_node(node, lang, config)
        if entry:
            results.append(entry)

        for child in node.children:
            self._traverse(child, results, lang)

    def _classify_node(self, node: Node, lang: str, config: Any) -> dict | None:
        ntype = node.type
        if ntype in config.definition_types:
            name = self._extract_name(node, lang)
            return _make_entry("definition", node, name) if name else None
        if ntype in config.import_types:
            name = _IMPORT_HANDLERS.get(lang, _get_import_generic)(node)
            return _make_entry("import", node, name) if name else None
        if ntype in config.call_types:
            name = _get_call_name(node)
            return _make_entry("call", node, name) if name else None
        return None

    # -- name extraction ---------------------------------------------------

    @staticmethod
    def _extract_name(node: Node, lang: str) -> str | None:
        ident = _first_child_text(node, ("identifier", "type_identifier", "name"))
        if ident:
            return ident

        override = _NAME_OVERRIDES.get(lang)
        if override:
            return override(node)

        return _field_text(node, "name")

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _lang_for(file_path: str) -> str | None:
        return EXTENSION_MAP.get(os.path.splitext(file_path)[1].lower())

    @property
    def parsers(self) -> dict[str, object | None]:
        return self._parsers

    @property
    def languages(self) -> dict[str, object | None]:
        return self._parsers


def _make_entry(entry_type: str, node: Node, name: str) -> dict:
    return {
        "type": entry_type,
        "kind": node.type,
        "name": name,
        "start_line": node.start_point[0] + 1,
        "end_line": node.end_point[0] + 1,
        "content": node.text.decode("utf-8") if node.text else "",
    }
