"""
Crate/package context for review — detects workspace membership and
checks for external usage of removed public symbols.
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger("clew.review.crate_context")


def gather_file_notes(file_path: str, diff: str, repo_root: str) -> list[str]:
    """Return structured notes about the file's package context.

    These are injected into the LLM prompt so it can make informed
    decisions about external-consumer risk.
    """
    notes: list[str] = []

    # Rust-specific: check if this is a workspace-internal crate
    if file_path.endswith(".rs"):
        crate_note = _check_rust_crate(file_path, repo_root)
        if crate_note:
            notes.append(crate_note)

    # Check for removed public symbols with zero remaining usage
    removed = _extract_removed_public_symbols(diff, file_path)
    for symbol in removed:
        hits = _grep_symbol(symbol, file_path, repo_root)
        if hits == 0:
            notes.append(f"Removed public symbol `{symbol}` has zero remaining references in the codebase.")
        elif hits > 0:
            notes.append(f"Removed public symbol `{symbol}` still has {hits} reference(s) elsewhere in the codebase.")

    return notes


def _check_rust_crate(file_path: str, repo_root: str) -> str | None:
    """Check if a .rs file belongs to a workspace-internal crate."""
    # Walk up from the file to find Cargo.toml
    parts = file_path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        candidate = os.path.join(repo_root, *parts[:i], "Cargo.toml")
        if os.path.exists(candidate):
            try:
                content = open(candidate, encoding="utf-8").read()
                if "publish = false" in content:
                    return "This crate has `publish = false` — no external consumers are possible."
                # Check for workspace membership via path deps
                if re.search(r'path\s*=\s*"\.\./', content):
                    # Has relative path deps — strong signal it's workspace-internal
                    # Check root for [workspace]
                    root_cargo = os.path.join(repo_root, "Cargo.toml")
                    if os.path.exists(root_cargo):
                        root_content = open(root_cargo, encoding="utf-8").read()
                        if "[workspace]" in root_content:
                            return (
                                "This crate is a workspace member with path dependencies — "
                                "it is not published and has no external consumers."
                            )
            except Exception:
                pass
            break
    return None


def _extract_removed_public_symbols(diff: str, file_path: str) -> list[str]:
    """Extract public symbols removed in the diff (pub mod, pub fn, pub struct, etc.)."""
    symbols: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("-"):
            continue
        line = line[1:].strip()
        # Rust: pub mod, pub fn, pub struct, pub enum, pub trait
        m = re.match(r"pub\s+(?:mod|fn|struct|enum|trait|type|use)\s+(\w+)", line)
        if m:
            symbols.append(m.group(1))
        # Python: from X import Y (removed), def X, class X
        m = re.match(r"(?:def|class)\s+(\w+)", line)
        if m:
            symbols.append(m.group(1))
    return symbols


def _grep_symbol(symbol: str, file_path: str, repo_root: str) -> int:
    """Count files referencing a removed public symbol as a qualified path.

    For Rust, searches for ``crate_name::symbol`` or ``mod::symbol`` patterns
    rather than the bare symbol name to avoid false matches.
    """
    # Build qualified patterns to grep for
    patterns = [f"::{symbol}"]  # use crate::content, use super::content
    # Also try the bare `mod symbol` / `use symbol` pattern
    patterns.append(f"mod {symbol}")
    patterns.append(f"use {symbol}")

    try:
        matching_files: set[str] = set()
        norm_exclude = "./" + file_path.lstrip("./")

        for pattern in patterns:
            cmd = [
                "grep",
                "-r",
                "--include=*.rs",
                "--include=*.py",
                "--include=*.ts",
                "--include=*.js",
                "--include=*.go",
                "-l",
                pattern,
                ".",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root, timeout=10)
            if result.returncode == 0:
                for f in result.stdout.strip().splitlines():
                    f = f.strip()
                    if f and f != norm_exclude:
                        matching_files.add(f)

        return len(matching_files)
    except Exception as exc:
        logger.debug("grep for %s failed: %s", symbol, exc)
        return -1
