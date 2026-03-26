"""Editor setup for Clew MCP tool integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CLEW_MARKER = "<!-- clew:setup -->"


@dataclass
class EditorConfig:
    """Configuration for an editor's instruction file."""

    path: str
    mode: str  # "append" or "create"
    detect: list[str]  # files/dirs whose existence signals this editor


EDITORS: dict[str, EditorConfig] = {
    "claude-code": EditorConfig(
        path="CLAUDE.md",
        mode="append",
        detect=["CLAUDE.md", ".claude/"],
    ),
    "cursor": EditorConfig(
        path=".cursor/rules/clew.mdc",
        mode="create",
        detect=[".cursor/", ".cursorignore"],
    ),
    "copilot": EditorConfig(
        path=".github/copilot-instructions.md",
        mode="append",
        detect=[".github/"],
    ),
    "gemini": EditorConfig(
        path="GEMINI.md",
        mode="append",
        detect=["GEMINI.md", ".gemini/"],
    ),
    "windsurf": EditorConfig(
        path=".windsurf/rules/clew.md",
        mode="create",
        detect=[".windsurf/"],
    ),
    "antigravity": EditorConfig(
        path="ANTIGRAVITY.md",
        mode="append",
        detect=["ANTIGRAVITY.md"],
    ),
}


def _core_directive() -> str:
    """Return the core Clew directive content."""
    return """\
## Clew Code Intelligence

Use the Clew MCP tools for codebase exploration instead of raw file reads:

- `search_codebase` — Find code relevant to a query with semantic + graph search
- `explore_module` — Analyze a module's dependencies and API
- `verify_concept` — Check if a library/pattern exists before deep analysis
- `list_repos` — List indexed repositories

Prefer Clew tools over Glob/Grep/Read when exploring unfamiliar code.
Only fall back to direct file reads for specific known paths."""


def _format_for_editor(editor: str) -> str:
    """Return the full file content / append block for a given editor."""
    core = _core_directive()

    if editor == "cursor":
        return (
            "---\n"
            "description: Use Clew MCP tools for intelligent code search\n"
            "globs:\n"
            "alwaysApply: true\n"
            "---\n\n"
            f"{CLEW_MARKER}\n\n"
            f"{core}\n"
        )

    # All other editors: markdown with marker
    return f"\n{CLEW_MARKER}\n\n{core}\n"


def detect_editors(project_dir: Path) -> list[str]:
    """Detect which editors are present in the project directory."""
    found: list[str] = []
    for name, cfg in EDITORS.items():
        for signal in cfg.detect:
            target = project_dir / signal
            if target.exists():
                found.append(name)
                break
    return found


def setup_editor(editor: str, project_dir: Path, force: bool = False) -> str:
    """Write editor instruction file. Returns a status message."""
    cfg = EDITORS[editor]
    target = project_dir / cfg.path
    existing = target.read_text() if target.exists() else ""

    if CLEW_MARKER in existing and not force:
        return f"[skip] {cfg.path} already contains Clew directives. Use --force to overwrite."

    content = _format_for_editor(editor)
    target.parent.mkdir(parents=True, exist_ok=True)

    if cfg.mode == "append" and existing:
        base = existing.split(CLEW_MARKER)[0].rstrip() if (force and CLEW_MARKER in existing) else existing
        target.write_text(base + content)
    else:
        target.write_text(content)

    return f"[ok] Wrote Clew directives to {cfg.path}"
