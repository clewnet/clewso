import asyncio
import json
import os
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .client import ClewAPIClient
from .config import get_config
from .review.context import fetch_review_context
from .review.graph import get_impact_radius
from .review.llm import analyze_impact
from .setup import EDITORS, detect_editors, setup_editor


def _version_callback(value: bool) -> None:
    if value:
        print(f"clewso {__version__}")
        raise typer.Exit()


app = typer.Typer(name="clewso", help="🧶 Clewso - Context Engine for AI Agents", add_completion=False)
console = Console()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit"
    ),
) -> None:
    """Clewso - Context Engine for AI Agents."""


def get_git_diff(staged: bool = False, pr: bool = False) -> str:
    """Get the diff of the current repo."""
    if pr:
        cmd = ["git", "diff", "origin/main...HEAD"]
    elif staged:
        cmd = ["git", "diff", "--staged"]
    else:
        cmd = ["git", "diff"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


def get_file_diffs(diff: str) -> dict[str, str]:
    """
    Parse diff to retrieve the DIFF CONTENT for each file.
    Note: Previous implementation only returned added lines.
    We need the full file section of the diff for LLM analysis.
    """
    file_map = {}
    current_file = None
    current_content = []

    for line in diff.splitlines():
        if line.startswith("diff --git"):
            if current_file:
                file_map[current_file] = "\n".join(current_content)

            current_content = [line]
            parts = line.split()
            if len(parts) >= 3:
                path = parts[-1]
                if path.startswith("b/"):
                    current_file = path[2:]
                elif path.startswith("a/"):
                    current_file = path[2:]
                else:
                    current_file = path
        else:
            if current_file:
                current_content.append(line)

    if current_file:
        file_map[current_file] = "\n".join(current_content)

    return file_map


async def analyze_change_smart(client: ClewAPIClient, file_path: str, file_diff: str, repo_root: str) -> dict:
    """Run the 3-stage Smart Review pipeline."""
    try:
        # Stage 1: Impact Graph
        impacts = await get_impact_radius(client, file_path, limit=10)

        # Stage 2: Context
        context = fetch_review_context(impacts, repo_root)

        # Stage 3: Reasoning
        result = await analyze_impact(file_diff, context, file_path)

        return {
            "path": file_path,
            "risk_level": result.risk_level,
            "explanation": result.explanation,
            "impact_count": len(impacts),
            "affected_files": result.affected_files,
            "recommendation": result.recommendation,
        }
    except Exception as e:
        return {
            "path": file_path,
            "risk_level": "UNKNOWN",
            "explanation": str(e),
            "impact_count": 0,
            "affected_files": [],
            "recommendation": "Manual review required error",
        }


async def _run_analysis(files: list[str], file_diffs: dict[str, str], repo_root: str) -> list[dict]:
    """Run analysis on changed files."""
    cfg = get_config()
    async with ClewAPIClient(base_url=cfg.api.url, api_key=cfg.api.key or None) as client:
        tasks = [analyze_change_smart(client, f, file_diffs[f], repo_root) for f in files]
        return await asyncio.gather(*tasks)


async def _run_dry_run(files: list[str], file_diffs: dict[str, str], repo_root: str) -> dict:
    """Run dry-run analysis: impact analysis + policy checks."""
    from .review.policy import check_policies, fetch_policies

    cfg = get_config()
    async with ClewAPIClient(base_url=cfg.api.url, api_key=cfg.api.key or None) as client:
        # Run impact analysis and policy fetch in parallel
        import asyncio as _asyncio

        analysis_task = _asyncio.create_task(
            _asyncio.gather(*[analyze_change_smart(client, f, file_diffs[f], repo_root) for f in files])
        )
        policies_task = _asyncio.create_task(fetch_policies(client))

        results, policies = await _asyncio.gather(analysis_task, policies_task)

        # Check policies against changed files
        violations = check_policies(policies, files, file_diffs)

    return {
        "files_analyzed": len(files),
        "impact_results": list(results),
        "violations": [
            {
                "rule_id": v.rule_id,
                "rule_type": v.rule_type,
                "severity": v.severity,
                "message": v.message,
                "file_path": v.file_path,
                "matched_pattern": v.matched_pattern,
            }
            for v in violations
        ],
        "has_blockers": any(v.severity == "block" for v in violations),
    }


def _render_dry_run_output(result: dict, output_format: str):
    """Render dry-run results."""
    if output_format == "json":
        print(json.dumps(result, indent=2))
        return

    # Markdown / Rich both get the markdown format for dry-run
    print("# Dry-Run Review Results\n")
    print(f"**Files analyzed**: {result['files_analyzed']}")

    violations = result.get("violations", [])
    if violations:
        print(f"\n## Policy Violations ({len(violations)})\n")
        for v in violations:
            icon = (
                "\U0001f6ab"
                if v["severity"] == "block"
                else "\u26a0\ufe0f"
                if v["severity"] == "warn"
                else "\U0001f4cb"
            )
            print(f"- {icon} **[{v['severity'].upper()}]** `{v['file_path']}`: {v['message']}")
            print(f"  Rule: `{v['rule_id']}` | Pattern: `{v['matched_pattern']}`")
    else:
        print("\n## Policy Violations\n\nNo violations found. \u2705")

    # Impact summary
    impact_results = result.get("impact_results", [])
    if impact_results:
        print(f"\n## Impact Analysis ({len(impact_results)} files)\n")
        for res in impact_results:
            icon = (
                "\U0001f534"
                if res["risk_level"] == "HIGH"
                else "\U0001f7e1"
                if res["risk_level"] == "MEDIUM"
                else "\U0001f7e2"
            )
            print(f"- {icon} `{res['path']}` \u2014 {res['risk_level']} ({res['impact_count']} downstream)")

    if result.get("has_blockers"):
        print("\n---\n**Result: BLOCKED** \u2014 Blocking policy violations found.")
    else:
        print("\n---\n**Result: PASS** \u2014 No blocking violations.")


def _render_markdown_results(results: list[dict]):
    """Render results in Markdown."""
    print("# Smart Context-Aware Review\n")

    for res in results:
        icon = "✅"
        if res["risk_level"] == "HIGH":
            icon = "🔴"
        elif res["risk_level"] == "MEDIUM":
            icon = "🟡"
        elif res["risk_level"] == "LOW":
            icon = "🟢"

        print(f"## {icon} {res['path']}")
        print(f"**Risk**: {res['risk_level']}")
        print(f"**Impact**: {res['impact_count']} downstream files found.")
        print(f"\n> {res['explanation']}\n")

        if res["affected_files"]:
            print("**Risk Details:**")
            for aff in res["affected_files"]:
                print(f"- `{aff}`")
        print(f"\n**Recommendation**: {res['recommendation']}\n")
        print("---\n")


def _render_rich_results(results: list[dict]):
    """Render results in Rich table."""
    table = Table(title="Context-Aware Review Results")
    table.add_column("File", style="cyan")
    table.add_column("Risk", justify="center")
    table.add_column("Impact", justify="right")
    table.add_column("Explanation")

    for res in results:
        risk_style = "green"
        if res["risk_level"] == "HIGH":
            risk_style = "bold red"
        elif res["risk_level"] == "MEDIUM":
            risk_style = "yellow"

        table.add_row(
            res["path"],
            f"[{risk_style}]{res['risk_level']}[/{risk_style}]",
            str(res["impact_count"]),
            res["explanation"],
        )

    console.print(table)


def _render_review_output(results: list[dict], output_format: str):
    """Render review results."""
    if output_format == "markdown":
        _render_markdown_results(results)
    else:
        _render_rich_results(results)


@app.command()
def review(
    staged: bool = typer.Option(False, "--staged", help="Analyze staged changes"),
    pr: bool = typer.Option(False, "--pr", help="Analyze PR (diff against origin/main)"),
    output: str = typer.Option("markdown", "--output", help="Output format: rich, markdown, json"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Analyze without writes; report policy violations and exit 1 if blocking"
    ),
):
    """
    Smart Context-Aware Review.
    """
    diff_text = get_git_diff(staged=staged, pr=pr)
    if not diff_text:
        console.print("No changes found.")
        if dry_run:
            raise typer.Exit(0)
        return

    # Use the new detailed diff parser
    try:
        file_diffs = get_file_diffs(diff_text)
    except Exception as e:
        console.print(f"[bold red]Error parsing diff:[/bold red] {e}")
        return

    files = list(file_diffs.keys())

    if not files:
        console.print("No changed files detected.")
        if dry_run:
            raise typer.Exit(0)
        return

    if not (dry_run and output == "json"):
        console.print(f"Analyzing {len(files)} changed files...")

    repo_root = os.getcwd()

    if dry_run:
        dry_run_result = asyncio.run(_run_dry_run(files, file_diffs, repo_root))
        _render_dry_run_output(dry_run_result, output)
        has_blockers = any(v["severity"] == "block" for v in dry_run_result.get("violations", []))
        raise typer.Exit(1 if has_blockers else 0)

    results = asyncio.run(_run_analysis(files, file_diffs, repo_root))

    # Render Output
    _render_review_output(results, output)


@app.command()
def index(
    repo_path: str = typer.Argument(..., help="Local path to a git repository"),
    repo_id: str | None = typer.Option(None, "--repo-id", help="Repository identifier (auto-generated if omitted)"),
    incremental: bool = typer.Option(False, "--incremental", help="Only index files changed since last indexed commit"),
):
    """Index a local git repository into Clewso."""
    repo_dir = Path(repo_path).resolve()
    if not repo_dir.is_dir():
        console.print(f"[bold red]Error:[/bold red] {repo_path} is not a valid directory")
        raise typer.Exit(1)

    cfg = get_config()
    write_mode = cfg.ci.write_mode.lower()
    if write_mode == "ci-only" and not cfg.ci.ci_token:
        console.print(
            "[bold red]Error:[/bold red] Write mode is ci-only. Ingestion requires a CI token (set CLEW_CI_TOKEN)."
        )
        raise typer.Exit(1)

    try:
        from clewso_ingestion.ingest import ingest_repo as _ingest_repo
        from clewso_ingestion.ingest import ingest_repo_incremental as _ingest_incremental
    except ImportError:
        console.print(
            "[bold red]Error:[/bold red] clewso-ingestion package is not installed. Run: pip install clewso-ingestion"
        )
        raise typer.Exit(1) from None

    if incremental:
        exit_code = _ingest_incremental(repo_id, str(repo_dir))
    else:
        exit_code = _ingest_repo(repo_id, str(repo_dir))

    raise typer.Exit(exit_code)


@app.command("setup-editor")
def setup_editor_cmd(
    editor: str | None = typer.Argument(
        None,
        help="Editor to configure (claude-code|cursor|copilot|gemini|windsurf|antigravity|all)",
    ),
    dir: Path = typer.Option(".", "--dir", help="Project directory"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing Clewso config even if marker found"),
):
    """Configure editor AI agents to use Clewso MCP tools."""
    project_dir = dir.resolve()

    if editor == "all":
        editors = list(EDITORS.keys())
    elif editor is not None:
        if editor not in EDITORS:
            console.print(f"[bold red]Unknown editor:[/bold red] {editor}")
            console.print(f"Supported: {', '.join(EDITORS.keys())}, all")
            raise typer.Exit(1)
        editors = [editor]
    else:
        # Auto-detect
        editors = detect_editors(project_dir)
        if not editors:
            console.print("No editors detected — configuring all.")
            editors = list(EDITORS.keys())
        else:
            console.print(f"Detected editors: {', '.join(editors)}")

    for ed in editors:
        msg = setup_editor(ed, project_dir, force=force)
        console.print(msg)


@app.command()
def serve(
    host: str = typer.Option(None, "--host", help="Bind host"),
    port: int = typer.Option(None, "--port", help="Bind port"),
):
    """Start the Clewso API server."""
    try:
        import uvicorn

        from .server.main import app as fastapi_app  # noqa: F811
    except ImportError:
        console.print("[bold red]Error:[/bold red] Server dependencies not installed. Run: pip install clewso[server]")
        raise typer.Exit(1) from None

    cfg = get_config()
    uvicorn.run(
        fastapi_app,
        host=host or cfg.server.host,
        port=port or cfg.server.port,
    )


@app.command("mcp")
def mcp_cmd():
    """Start the Clewso MCP tool server."""
    try:
        from .mcp.server import mcp  # noqa: F811
    except ImportError:
        console.print("[bold red]Error:[/bold red] MCP dependencies not installed. Run: pip install clewso[mcp]")
        raise typer.Exit(1) from None

    mcp.run()


@app.command()
def init():
    """Interactive setup — configure API keys and store connections."""
    from .config import ClewsoConfig, save_config

    console.print("[bold]Clewso Setup[/bold]\n")

    cfg = ClewsoConfig()

    # Embeddings
    provider = typer.prompt("Embedding provider (openai/ollama)", default="openai")
    cfg.embeddings.provider = provider
    if provider == "openai":
        key = typer.prompt("OpenAI API key", default="", hide_input=True)
        if key:
            cfg.embeddings.openai_api_key = key
    elif provider == "ollama":
        url = typer.prompt("Ollama URL", default=cfg.embeddings.ollama_url)
        cfg.embeddings.ollama_url = url

    # Store
    console.print("\n[bold]Backing stores[/bold] (press Enter for defaults)\n")
    cfg.store.qdrant_host = typer.prompt("Qdrant host", default=cfg.store.qdrant_host)
    cfg.store.qdrant_port = int(typer.prompt("Qdrant port", default=str(cfg.store.qdrant_port)))
    cfg.store.neo4j_uri = typer.prompt("Neo4j URI", default=cfg.store.neo4j_uri)

    path = save_config(cfg)
    console.print(f"\n[green]Saved to {path}[/green]")


@app.command("config")
def config_cmd(
    action: str = typer.Argument("show", help="Action: show or set"),
    key: str = typer.Argument(None, help="Config key (e.g. embeddings.provider)"),
    value: str = typer.Argument(None, help="New value"),
):
    """Show or modify configuration."""
    from .config import redact, save_config

    cfg = get_config()

    if action == "show":
        _show_config(cfg)
    elif action == "set":
        if not key or value is None:
            console.print("[bold red]Usage:[/bold red] clewso config set <section.field> <value>")
            raise typer.Exit(1)
        _set_config_value(cfg, key, value)
        save_config(cfg)
        console.print(f"[green]Set {key} = {redact(value) if 'key' in key or 'password' in key else value}[/green]")
    else:
        console.print(f"[bold red]Unknown action:[/bold red] {action}. Use 'show' or 'set'.")
        raise typer.Exit(1)


def _show_config(cfg: object) -> None:
    """Print resolved config with secrets redacted."""
    from dataclasses import fields as dc_fields

    from .config import redact

    secret_fields = {"openai_api_key", "key", "ci_token", "neo4j_password"}

    for section_name in ("api", "embeddings", "store", "server", "review", "ci"):
        section = getattr(cfg, section_name)
        console.print(f"\n[bold][{section_name}][/bold]")
        for f in dc_fields(section):
            val = getattr(section, f.name)
            display = redact(str(val)) if f.name in secret_fields and val else str(val)
            console.print(f"  {f.name} = {display}")


def _set_config_value(cfg: object, key: str, value: str) -> None:
    """Set a dotted config key (e.g. 'embeddings.provider')."""
    if "." not in key:
        console.print("[bold red]Key must be section.field format[/bold red] (e.g. embeddings.provider)")
        raise typer.Exit(1)
    section_name, field_name = key.split(".", 1)
    section = getattr(cfg, section_name, None)
    if section is None:
        console.print(f"[bold red]Unknown section:[/bold red] {section_name}")
        raise typer.Exit(1)
    if not hasattr(section, field_name):
        console.print(f"[bold red]Unknown field:[/bold red] {field_name} in [{section_name}]")
        raise typer.Exit(1)
    from .config import _coerce

    current = getattr(section, field_name)
    setattr(section, field_name, _coerce(value, current))


if __name__ == "__main__":
    app()
