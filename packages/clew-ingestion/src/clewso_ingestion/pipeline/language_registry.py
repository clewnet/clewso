"""
Language Registry

Data-driven configuration for tree-sitter language support.
Language definitions are stored in ``data/languages.toml`` and loaded at
import time.  To add a new language, append a ``[[language]]`` block to
that file -- no Python changes required.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LanguageConfig:
    """Configuration for a single tree-sitter language grammar."""

    name: str
    extensions: tuple[str, ...]
    definition_types: frozenset[str] = field(default_factory=frozenset)
    import_types: frozenset[str] = field(default_factory=frozenset)
    call_types: frozenset[str] = field(default_factory=frozenset)


_DATA_DIR = Path(__file__).parent / "data"


def _load_configs() -> dict[str, LanguageConfig]:
    """Load language configs from ``data/languages.toml``."""
    with open(_DATA_DIR / "languages.toml", "rb") as f:
        data = tomllib.load(f)
    return {
        lang["name"]: LanguageConfig(
            name=lang["name"],
            extensions=tuple(lang["extensions"]),
            definition_types=frozenset(lang.get("definition_types", ())),
            import_types=frozenset(lang.get("import_types", ())),
            call_types=frozenset(lang.get("call_types", ())),
        )
        for lang in data["language"]
    }


LANGUAGE_CONFIGS: dict[str, LanguageConfig] = _load_configs()


def build_extension_map() -> dict[str, str]:
    """Build a flat mapping from file extension to tree-sitter language name."""
    return {ext: cfg.name for cfg in LANGUAGE_CONFIGS.values() for ext in cfg.extensions}


EXTENSION_MAP: dict[str, str] = build_extension_map()
