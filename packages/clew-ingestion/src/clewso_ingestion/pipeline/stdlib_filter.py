"""
Stdlib / vendor module filter.

Prevents noisy IMPORTS edges to stdlib modules (os, json, logging, ...)
and common vendor packages during ingestion.

Extracted to its own module to avoid circular imports between
processing stages and node processors.
"""

from pathlib import Path

try:
    import sys as _sys

    STDLIB_MODULE_NAMES: frozenset[str] = frozenset(_sys.stdlib_module_names)  # Python 3.10+
except AttributeError:
    _DATA_DIR = Path(__file__).parent / "data"
    STDLIB_MODULE_NAMES = frozenset(
        line.strip()
        for line in (_DATA_DIR / "stdlib_fallback.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )

VENDOR_MODULE_NAMES: frozenset[str] = frozenset({"setuptools", "pip", "pkg_resources", "distlib", "wheel"})

SKIP_IMPORT_MODULES: frozenset[str] = STDLIB_MODULE_NAMES | VENDOR_MODULE_NAMES


def is_stdlib_or_vendor(module_name: str) -> bool:
    """Return True if *module_name* is stdlib or a known vendor package."""
    top_level = module_name.split(".")[0]
    return top_level in SKIP_IMPORT_MODULES
