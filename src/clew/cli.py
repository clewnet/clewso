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


app = typer.Typer(name="clewso", help="🧶👀 Clewso - Context Engine for AI Agents", add_completion=False)
console = Console()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit"
    ),
) -> None:
    """Clewso - Context Engine for AI Agents."""


_SKIP_FILES = frozenset(
    {
        "Cargo.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "uv.lock",
        "poetry.lock",
        "Gemfile.lock",
        "composer.lock",
        "Pipfile.lock",
        "go.sum",
    }
)

_SKIP_EXTENSIONS = frozenset({".lock", ".sum"})


def _is_skip_file(path: str) -> bool:
    """Return True for lockfiles and generated files that don't need review."""
    basename = path.rsplit("/", 1)[-1]
    _, ext = os.path.splitext(basename)
    return basename in _SKIP_FILES or ext in _SKIP_EXTENSIONS


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


async def analyze_change_smart(
    client: ClewAPIClient,
    file_path: str,
    file_diff: str,
    repo_root: str,
    changed_files: set[str] | None = None,
    deleted_files: set[str] | None = None,
) -> dict:
    """Run the 3-stage Smart Review pipeline."""
    try:
        # Stage 1: Impact Graph
        impacts = await get_impact_radius(
            client, file_path, limit=10, changed_files=changed_files, deleted_files=deleted_files
        )

        # Stage 2: Context
        context = fetch_review_context(impacts, repo_root)

        # Stage 2b: Package context (workspace membership, symbol grep)
        from .review.crate_context import gather_file_notes

        notes = gather_file_notes(file_path, file_diff, repo_root)

        # Stage 3: Reasoning
        result = await analyze_impact(file_diff, context, file_path, impacts=impacts, notes=notes)

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
    changed = set(files)
    deleted = {f for f in files if not os.path.exists(os.path.join(repo_root, f))}
    async with ClewAPIClient(base_url=cfg.api.url, api_key=cfg.api.key or None) as client:
        tasks = [analyze_change_smart(client, f, file_diffs[f], repo_root, changed, deleted) for f in files]
        return await asyncio.gather(*tasks)


async def _run_dry_run(files: list[str], file_diffs: dict[str, str], repo_root: str) -> dict:
    """Run dry-run analysis: impact analysis + policy checks."""
    from .review.policy import check_policies, fetch_policies

    cfg = get_config()
    async with ClewAPIClient(base_url=cfg.api.url, api_key=cfg.api.key or None) as client:
        # Run impact analysis and policy fetch in parallel
        import asyncio as _asyncio

        results, policies = await _asyncio.gather(
            _asyncio.gather(*[analyze_change_smart(client, f, file_diffs[f], repo_root) for f in files]),
            fetch_policies(client),
        )

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


def _render_markdown_file(res: dict) -> None:
    """Render a single file result in Markdown."""
    icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢", "SAFE": "✅"}.get(res["risk_level"], "❓")
    print(f"## {icon} {res['path']} — {res['risk_level']}")
    print(f"**Impact**: {res['impact_count']} downstream files\n")
    print(f"> {res['explanation']}\n")
    if res["affected_files"]:
        print("**Affected:**")
        for aff in res["affected_files"]:
            print(f"- `{aff}`")
    print(f"\n**Recommendation**: {res['recommendation']}\n")
    print("---\n")


def _render_markdown_results(results: list[dict], verbose: bool = False):
    """Render results in Markdown."""
    flagged = [r for r in results if r["risk_level"] not in ("SAFE", "UNKNOWN")]
    safe = [r for r in results if r["risk_level"] in ("SAFE", "UNKNOWN")]

    if not verbose and not flagged:
        print(f"All {len(results)} files passed review (SAFE).")
        return

    if flagged:
        print("# Review Findings\n")
        for res in flagged:
            _render_markdown_file(res)

    if safe and not verbose:
        print(f"✅ {len(safe)} file(s) passed (SAFE)\n")
    elif verbose:
        for res in safe:
            _render_markdown_file(res)


def _render_rich_results(results: list[dict], verbose: bool = False):
    """Render results in Rich table."""
    flagged = [r for r in results if r["risk_level"] not in ("SAFE", "UNKNOWN")]
    safe = [r for r in results if r["risk_level"] in ("SAFE", "UNKNOWN")]

    show = results if verbose else flagged

    if show:
        table = Table(title="Review Findings" if not verbose else "Context-Aware Review Results")
        table.add_column("File", style="cyan")
        table.add_column("Risk", justify="center")
        table.add_column("Impact", justify="right")
        table.add_column("Explanation")

        for res in show:
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

    if safe and not verbose:
        console.print(f"\n[green]✅ {len(safe)} file(s) passed (SAFE)[/green]")
    elif not show and not safe:
        console.print("No files to review.")


def _render_review_output(results: list[dict], output_format: str, verbose: bool = False):
    """Render review results."""
    if output_format == "markdown":
        _render_markdown_results(results, verbose=verbose)
    else:
        _render_rich_results(results, verbose=verbose)


@app.command()
def review(
    staged: bool = typer.Option(False, "--staged", help="Analyze staged changes"),
    pr: bool = typer.Option(False, "--pr", help="Analyze PR (diff against origin/main)"),
    output: str = typer.Option("markdown", "--output", help="Output format: rich, markdown, json"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show full details for all files (default: only flagged)"
    ),
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

    files = [f for f in file_diffs if not _is_skip_file(f)]

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
    _render_review_output(results, output, verbose=verbose)


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

    from dataclasses import asdict

    sc = asdict(cfg.store)
    sc["graph_adapter"] = cfg.server.graph_adapter
    sc["vector_adapter"] = cfg.server.vector_adapter
    sc["embedding_dimension"] = cfg.embeddings.dimension

    try:
        if incremental:
            exit_code = _ingest_incremental(repo_id, str(repo_dir), store_config=sc)
        else:
            exit_code = _ingest_repo(repo_id, str(repo_dir), store_config=sc)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow] — pending writes flushed.")
        raise typer.Exit(130) from None

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
def init(
    force: bool = typer.Option(False, "--force", help="Re-run setup even if config exists"),
):
    """Interactive setup — configure API keys and store connections."""
    from .config import CONFIG_FILE, load_config, save_config

    console.print("[bold]Clewso Setup[/bold]\n")

    if CONFIG_FILE.is_file() and not force:
        console.print(f"Config already exists at [cyan]{CONFIG_FILE}[/cyan]")
        console.print(
            "Run [bold]clewso init --force[/bold] to reconfigure,"
            " or [bold]clewso config set <key> <value>[/bold] to update individual settings."
        )
        raise typer.Exit(0)

    # Start from the fully resolved config (file + env) so existing values
    # appear as defaults in the prompts.
    cfg = load_config()

    # Embeddings
    provider = typer.prompt("Embedding provider (openai/ollama)", default=cfg.embeddings.provider)
    cfg.embeddings.provider = provider
    if provider == "openai":
        key = typer.prompt("OpenAI API key", default="", hide_input=True)
        if key:
            cfg.embeddings.openai_api_key = key
    elif provider == "ollama":
        url = typer.prompt("Ollama URL", default=cfg.embeddings.ollama_url)
        cfg.embeddings.ollama_url = url

    # Store backend
    store_mode = typer.prompt(
        "Store backend (ladybug/server)", default="ladybug" if cfg.server.graph_adapter == "ladybug" else "server"
    )

    if store_mode == "ladybug":
        cfg.server.graph_adapter = "ladybug"
        cfg.server.vector_adapter = "ladybug"
        lb_path = typer.prompt("LadybugDB path", default=cfg.store.ladybug_path)
        cfg.store.ladybug_path = lb_path
    else:
        cfg.server.graph_adapter = "neo4j"
        cfg.server.vector_adapter = "qdrant"

        # Store — Qdrant
        console.print("\n[bold]Qdrant[/bold] (press Enter for defaults)\n")
        qdrant_url = typer.prompt("Qdrant URL (leave empty for host/port)", default=cfg.store.qdrant_url)
        cfg.store.qdrant_url = qdrant_url
        if qdrant_url:
            api_key = typer.prompt("Qdrant API key", default="", hide_input=True)
            if api_key:
                cfg.store.qdrant_api_key = api_key
        else:
            cfg.store.qdrant_host = typer.prompt("Qdrant host", default=cfg.store.qdrant_host)
            cfg.store.qdrant_port = int(typer.prompt("Qdrant port", default=str(cfg.store.qdrant_port)))

        # Store — Neo4j
        console.print("\n[bold]Neo4j[/bold]\n")
        cfg.store.neo4j_uri = typer.prompt("Neo4j URI", default=cfg.store.neo4j_uri)
        cfg.store.neo4j_user = typer.prompt("Neo4j user", default=cfg.store.neo4j_user)
        neo4j_pw = typer.prompt("Neo4j password", default="", hide_input=True)
        if neo4j_pw:
            cfg.store.neo4j_password = neo4j_pw

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

    secret_fields = {"openai_api_key", "key", "ci_token", "neo4j_password", "qdrant_api_key"}

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


# ---------------------------------------------------------------------------
# Hooks subcommand group
# ---------------------------------------------------------------------------

hooks_app = typer.Typer(name="hooks", help="Manage git hooks for clewso review.")
app.add_typer(hooks_app)


@hooks_app.command("install")
def hooks_install(
    pre_commit: bool = typer.Option(True, "--pre-commit/--no-pre-commit", help="Install pre-commit hook"),
    pre_push: bool = typer.Option(False, "--pre-push/--no-pre-push", help="Install pre-push hook"),
):
    """Install git hooks that run clewso review on commit/push."""
    from .hooks import install

    types = []
    if pre_commit:
        types.append("pre-commit")
    if pre_push:
        types.append("pre-push")

    if not types:
        console.print("[yellow]No hook types selected.[/yellow]")
        raise typer.Exit(0)

    try:
        installed = install(types)
        for h in installed:
            console.print(f"[green]Installed[/green] {h} hook")
        if not installed:
            console.print("[yellow]No hooks installed.[/yellow]")
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1) from None


@hooks_app.command("uninstall")
def hooks_uninstall():
    """Remove all clewso git hooks (restores originals if backed up)."""
    from .hooks import uninstall

    try:
        removed = uninstall()
        for h in removed:
            console.print(f"[green]Removed[/green] {h} hook")
        if not removed:
            console.print("No clewso hooks found.")
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1) from None


@hooks_app.command("status")
def hooks_status():
    """Show git hook installation status."""
    from .hooks import status

    try:
        statuses = status()
        for hook_type, state in statuses.items():
            if "installed" in state:
                console.print(f"  [green]{hook_type}[/green]: {state}")
            elif "other" in state:
                console.print(f"  [yellow]{hook_type}[/yellow]: {state}")
            else:
                console.print(f"  [dim]{hook_type}[/dim]: {state}")
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# Query commands — direct store access, no server required
# ---------------------------------------------------------------------------


def _get_stores():
    """Lazy-import and instantiate stores from config."""
    from .stores import get_embeddings, get_graph_store, get_vector_store

    return get_vector_store(), get_graph_store(), get_embeddings()


def _connection_error_hint(e: Exception) -> None:
    """Print a helpful hint when store connections fail."""
    console.print(f"[bold red]Connection error:[/bold red] {e}")
    console.print("[dim]Ensure Qdrant/Neo4j are running and config is correct (clewso config show)[/dim]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Natural language search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Number of results"),
    repo: str = typer.Option(None, "--repo", "-r", help="Filter by repository name"),
    graph_context: bool = typer.Option(True, "--graph/--no-graph", help="Include graph context for top results"),
    output: str = typer.Option("rich", "--output", "-o", help="Output format: rich, json"),
):
    """Semantic search across indexed codebases."""
    asyncio.run(_search(query, limit, repo, graph_context, output))


async def _fetch_graph_context(graph_store, results) -> dict[str, dict]:
    """Fetch 1-hop graph context for the top 3 search results."""
    context_map: dict[str, dict] = {}
    for r in results[:3]:
        path = r.metadata.get("path", "")
        if not path:
            continue
        try:
            graph_data = await graph_store.traverse(
                start_id=path,
                depth=1,
                relationship_types=["IMPORTS", "CALLS", "DEFINES", "CONTAINS"],
            )
            context_map[path] = {
                "nodes": [{"id": n.id, "label": n.label} for n in graph_data.nodes],
                "edges": [{"source": e.source, "target": e.target, "type": e.type} for e in graph_data.edges],
            }
        except Exception:
            pass
    return context_map


def _render_search_result(index: int, r, context_map: dict[str, dict]) -> None:
    """Render a single search result with optional graph context."""
    path = r.metadata.get("path", "unknown")
    console.print(f"\n[bold cyan]{index}.[/bold cyan] [cyan]{path}[/cyan]  [dim](score: {r.score:.3f})[/dim]")
    snippet = r.content[:200].replace("\n", "\n   ")
    console.print(f"   {snippet}")

    ctx = context_map.get(path)
    if not ctx or not ctx.get("edges"):
        return
    edges = ctx["edges"]
    # Filter out trivial Repository CONTAINS edges
    outgoing = [e for e in edges if e["source"] == path and e["type"] != "CONTAINS"]
    incoming = [e for e in edges if e["target"] == path and e["type"] != "CONTAINS"]
    # Node id is the name/path (e.g. "auth.py", "search_codebase"), label is the type (e.g. "Module")
    node_labels = {n["id"]: n["label"] for n in ctx["nodes"]}
    if outgoing:
        names = [f"{e['target']} [{e['type']}]" for e in outgoing[:5]]
        console.print(f"   [dim]Depends on: {', '.join(names)}[/dim]")
    if incoming:
        names = [f"{e['source']} [{node_labels.get(e['source'], '')}]" for e in incoming[:5]]
        console.print(f"   [dim]Used by: {', '.join(names)}[/dim]")


async def _search(query: str, limit: int, repo: str | None, graph_context: bool, output: str):
    vector_store, graph_store, embeddings = _get_stores()

    try:
        query_vector = await embeddings.embed(query)
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    try:
        results = await vector_store.search(query_vector=query_vector, limit=limit, repo=repo)
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if not results:
        console.print("No results found.")
        raise typer.Exit(0)

    context_map = await _fetch_graph_context(graph_store, results) if graph_context else {}

    if output == "json":
        data = [
            {
                "id": r.id,
                "score": r.score,
                "path": r.metadata.get("path", ""),
                "content": r.content[:200],
                "graph": context_map.get(r.metadata.get("path", "")),
            }
            for r in results
        ]
        print(json.dumps(data, indent=2))
        return

    for i, r in enumerate(results):
        _render_search_result(i + 1, r, context_map)


@app.command()
def traverse(
    node_id: str = typer.Argument(..., help="Starting node ID or file path"),
    depth: int = typer.Option(2, "--depth", "-d", help="Traversal depth (1-3)", min=1, max=3),
    relationships: list[str] = typer.Option(
        ["IMPORTS", "CALLS", "DEFINES", "CONTAINS"],
        "--rel",
        "-R",
        help="Relationship types to follow",
    ),
    repo_id: str = typer.Option(None, "--repo-id", help="Repository ID to scope traversal"),
    output: str = typer.Option("rich", "--output", "-o", help="Output format: rich, json, mermaid"),
):
    """Traverse the code graph from a starting node."""
    asyncio.run(_traverse(node_id, depth, relationships, repo_id, output))


async def _traverse(node_id: str, depth: int, relationships: list[str], repo_id: str | None, output: str):
    _, graph_store, _ = _get_stores()

    try:
        result = await graph_store.traverse(
            start_id=node_id,
            depth=depth,
            relationship_types=relationships,
            repo_id=repo_id,
        )
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if output == "json":
        data = {
            "nodes": [{"id": n.id, "label": n.label, "properties": n.properties} for n in result.nodes],
            "edges": [
                {"source": e.source, "target": e.target, "type": e.type, "properties": e.properties}
                for e in result.edges
            ],
        }
        print(json.dumps(data, indent=2))
        return

    if output == "mermaid":
        from .mcp.formatters import GraphFormatter

        graph_dict = {
            "nodes": [{"id": n.id, "label": n.label} for n in result.nodes],
            "edges": [{"source": e.source, "target": e.target, "type": e.type} for e in result.edges],
        }
        print(GraphFormatter.build_mermaid_diagram(graph_dict, node_id))
        return

    # Rich table output
    if not result.nodes:
        console.print("No graph data found for this node.")
        raise typer.Exit(0)

    console.print(f"\n[bold]Graph from[/bold] [cyan]{node_id}[/cyan] [dim](depth={depth})[/dim]")
    console.print(f"[dim]{len(result.nodes)} nodes, {len(result.edges)} edges[/dim]\n")

    node_map = {n.id: n.label for n in result.nodes}

    table = Table(title="Edges")
    table.add_column("Source", style="cyan")
    table.add_column("Relationship", style="yellow", justify="center")
    table.add_column("Target", style="green")

    for e in result.edges:
        table.add_row(node_map.get(e.source, e.source), e.type, node_map.get(e.target, e.target))

    console.print(table)


@app.command()
def explore(
    path: str = typer.Argument(..., help="File path or module name to explore"),
    repo: str = typer.Option(None, "--repo", "-r", help="Repository name filter"),
    output: str = typer.Option("rich", "--output", "-o", help="Output format: rich, json, mermaid"),
):
    """Explore a module's dependencies, definitions, and usage."""
    asyncio.run(_explore(path, repo, output))


_OUTGOING_TYPE_LABELS = {"DEFINES": "Defines", "IMPORTS": "Dependencies", "CALLS": "Calls"}


def _categorize_edges(edges, node_id: str, node_map: dict[str, str]) -> dict[str, list[str]]:
    """Categorize graph edges into named sections relative to a focus node."""
    categorized: dict[str, list[str]] = {label: [] for label in (*_OUTGOING_TYPE_LABELS.values(), "Used by")}
    for e in edges:
        if e.source == node_id and e.type in _OUTGOING_TYPE_LABELS:
            categorized[_OUTGOING_TYPE_LABELS[e.type]].append(node_map.get(e.target, e.target))
        elif e.target == node_id:
            categorized["Used by"].append(f"{node_map.get(e.source, e.source)} ({e.type})")
    return categorized


def _render_explore_rich(found_path: str, node_id: str, result) -> None:
    """Render module exploration in Rich format."""
    console.print(f"\n[bold]Module Analysis:[/bold] [cyan]{found_path}[/cyan]\n")

    node_map = {n.id: n.label for n in result.nodes}
    categorized = _categorize_edges(result.edges, node_id, node_map)

    any_found = False
    for section, items in categorized.items():
        if items:
            any_found = True
            console.print(f"[bold]{section}:[/bold]")
            for item in items:
                console.print(f"  - {item}")
            console.print()

    if not any_found:
        console.print("[dim]No relationships found (isolated module).[/dim]")


async def _explore(path: str, repo: str | None, output: str):
    vector_store, graph_store, embeddings = _get_stores()

    try:
        query_vector = await embeddings.embed(path)
        results = await vector_store.search(query_vector=query_vector, limit=1, repo=repo)
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if not results:
        console.print(f"Could not find module matching '{path}'")
        raise typer.Exit(1)

    node = results[0]
    found_path = node.metadata.get("path", "unknown")

    try:
        result = await graph_store.traverse(
            start_id=found_path,
            depth=2,
            relationship_types=["IMPORTS", "DEFINES", "CALLS", "CONTAINS"],
        )
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if output == "json":
        data = {
            "path": found_path,
            "node_id": found_path,
            "nodes": [{"id": n.id, "label": n.label, "properties": n.properties} for n in result.nodes],
            "edges": [{"source": e.source, "target": e.target, "type": e.type} for e in result.edges],
        }
        print(json.dumps(data, indent=2))
        return

    if output == "mermaid":
        from .mcp.formatters import GraphFormatter

        graph_dict = {
            "nodes": [{"id": n.id, "label": n.label} for n in result.nodes],
            "edges": [{"source": e.source, "target": e.target, "type": e.type} for e in result.edges],
        }
        print(GraphFormatter.build_mermaid_diagram(graph_dict, found_path))
        return

    _render_explore_rich(found_path, found_path, result)


@app.command()
def verify(
    concept: str = typer.Argument(..., help="Concept, library, or pattern to verify"),
    repo: str = typer.Option(None, "--repo", "-r", help="Repository name filter"),
):
    """Check if a concept exists in the indexed codebase."""
    asyncio.run(_verify(concept, repo))


async def _verify(concept: str, repo: str | None):
    vector_store, _, embeddings = _get_stores()

    try:
        query_vector = await embeddings.embed(concept)
        results = await vector_store.search(query_vector=query_vector, limit=5, repo=repo)
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if not results:
        console.print(f"[bold red]NOT FOUND:[/bold red] '{concept}' does not exist in the codebase.")
        raise typer.Exit(1)

    console.print(f"[bold green]FOUND:[/bold green] '{concept}' in {len(results)} locations:\n")
    for r in results:
        path = r.metadata.get("path", "unknown")
        console.print(f"  - [cyan]{path}[/cyan] [dim](score: {r.score:.3f})[/dim]")


@app.command()
def stats(
    repo_id: str = typer.Option(None, "--repo-id", help="Repository ID filter"),
    output: str = typer.Option("rich", "--output", "-o", help="Output format: rich, json"),
):
    """Show graph statistics (node/edge counts, density)."""
    asyncio.run(_stats(repo_id, output))


async def _stats(repo_id: str | None, output: str):
    _, graph_store, _ = _get_stores()

    try:
        s = await graph_store.get_stats(repo_id=repo_id)
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if output == "json":
        print(json.dumps(s, indent=2))
        return

    table = Table(title="Graph Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Nodes", str(s.get("node_count", 0)))
    table.add_row("Edges", str(s.get("edge_count", 0)))
    table.add_row("Density", f"{s.get('density', 0.0):.4f}")

    console.print(table)


@app.command()
def prs(
    file_path: str = typer.Argument(..., help="File path to look up"),
    repo_id: str = typer.Option(None, "--repo-id", help="Repository ID filter"),
    output: str = typer.Option("rich", "--output", "-o", help="Output format: rich, json"),
):
    """Show pull requests that modified a file."""
    asyncio.run(_prs(file_path, repo_id, output))


async def _prs(file_path: str, repo_id: str | None, output: str):
    _, graph_store, _ = _get_stores()

    try:
        nodes = await graph_store.get_file_pull_requests(file_path, repo_id=repo_id)
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if output == "json":
        data = [{"id": n.id, "label": n.label, "properties": n.properties} for n in nodes]
        print(json.dumps(data, indent=2))
        return

    if not nodes:
        console.print(f"No PRs found for [cyan]{file_path}[/cyan]")
        raise typer.Exit(0)

    console.print(f"\n[bold]PRs modifying[/bold] [cyan]{file_path}[/cyan]\n")

    table = Table()
    table.add_column("PR", style="cyan")
    table.add_column("Details")

    for n in nodes:
        pr_label = n.label or n.id
        details = ", ".join(f"{k}: {v}" for k, v in n.properties.items() if k not in ("id",))
        table.add_row(pr_label, details or "-")

    console.print(table)


@app.command()
def impact(
    pr_number: int = typer.Argument(..., help="Pull request number"),
    repo_id: str = typer.Option(..., "--repo-id", help="Repository ID"),
    output: str = typer.Option("rich", "--output", "-o", help="Output format: rich, json"),
):
    """Show the impact of a pull request (files and functions modified)."""
    asyncio.run(_impact(pr_number, repo_id, output))


async def _impact(pr_number: int, repo_id: str, output: str):
    _, graph_store, _ = _get_stores()

    try:
        result = await graph_store.get_pr_impact(pr_number, repo_id)
    except Exception as e:
        _connection_error_hint(e)
        raise typer.Exit(1) from None

    if output == "json":
        data = {
            "nodes": [{"id": n.id, "label": n.label, "properties": n.properties} for n in result.nodes],
            "edges": [{"source": e.source, "target": e.target, "type": e.type} for e in result.edges],
        }
        print(json.dumps(data, indent=2))
        return

    if not result.nodes:
        console.print(f"No impact data found for PR #{pr_number}")
        raise typer.Exit(0)

    console.print(f"\n[bold]Impact of PR #{pr_number}[/bold]\n")

    files = [n for n in result.nodes if n.label in ("File", "file")]
    functions = [n for n in result.nodes if n.label not in ("File", "file", "PullRequest")]

    if files:
        console.print("[bold]Files modified:[/bold]")
        for f in files:
            console.print(f"  - [cyan]{f.properties.get('path', f.id)}[/cyan]")

    if functions:
        console.print("\n[bold]Functions/symbols affected:[/bold]")
        for fn in functions:
            console.print(f"  - {fn.properties.get('name', fn.id)} ({fn.label})")


@app.command()
def migrate(
    to: str = typer.Option(..., "--to", help="Target backend: ladybug or server"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="Compare counts before finalizing"),
):
    """Migrate data between LadybugDB (embedded) and server-mode stores (Neo4j + Qdrant)."""
    if to == "ladybug":
        asyncio.run(_migrate_to_ladybug(verify))
    elif to == "server":
        asyncio.run(_migrate_to_server(verify))
    else:
        console.print(f"[bold red]Unknown target:[/bold red] {to}. Use 'ladybug' or 'server'.")
        raise typer.Exit(1)


async def _migrate_to_ladybug(verify: bool):
    from .config import get_config, save_config
    from .stores import resolve_ladybug_path

    cfg = get_config()

    if cfg.server.graph_adapter == "ladybug" and cfg.server.vector_adapter == "ladybug":
        console.print("Already using LadybugDB. Nothing to migrate.")
        raise typer.Exit(0)

    # Source stores (use sync clients for migration)
    try:
        from .server.adapters import Neo4jStore

        neo4j = Neo4jStore(uri=cfg.store.neo4j_uri, user=cfg.store.neo4j_user, password=cfg.store.neo4j_password)

        from qdrant_client import QdrantClient

        if cfg.store.qdrant_url:
            qdrant_client = QdrantClient(url=cfg.store.qdrant_url, api_key=cfg.store.qdrant_api_key or None)
        else:
            qdrant_client = QdrantClient(host=cfg.store.qdrant_host, port=cfg.store.qdrant_port)
        qdrant_collection = cfg.store.qdrant_collection
    except Exception as e:
        console.print(f"[bold red]Cannot connect to source stores:[/bold red] {e}")
        raise typer.Exit(1) from None

    # Target store
    from pathlib import Path

    from .server.adapters import LadybugUnifiedStore

    lb_path = resolve_ladybug_path(cfg)
    Path(lb_path).parent.mkdir(parents=True, exist_ok=True)
    target = LadybugUnifiedStore(lb_path, cfg.embeddings.dimension)

    # Migrate graph: export all nodes and relationships from Neo4j
    console.print("\n[bold]Migrating graph data from Neo4j...[/bold]")
    source_stats = await neo4j.get_stats()
    console.print(f"  Source: {source_stats['node_count']} nodes, {source_stats['edge_count']} edges")

    _migrate_graph(neo4j, target)

    # Migrate vectors: scroll all points from Qdrant
    console.print("\n[bold]Migrating vectors from Qdrant...[/bold]")
    vector_count = _migrate_vectors(qdrant_client, qdrant_collection, target)
    console.print(f"  Migrated {vector_count} vectors")

    # Verify
    if verify:
        console.print("\n[bold]Verifying...[/bold]")
        target_stats = await target.get_stats()
        console.print(f"  Source: {source_stats['node_count']} nodes, {source_stats['edge_count']} edges")
        console.print(f"  Target: {target_stats['node_count']} nodes, {target_stats['edge_count']} edges")
        console.print(f"  Vectors: {vector_count} migrated")

        issues = []
        if target_stats["node_count"] == 0 and source_stats["node_count"] > 0:
            issues.append("target has 0 nodes but source has data")
        if source_stats["node_count"] > 0 and target_stats["node_count"] < source_stats["node_count"] * 0.5:
            issues.append(
                f"target has significantly fewer nodes ({target_stats['node_count']}) "
                f"than source ({source_stats['node_count']})"
            )
        if issues:
            for issue in issues:
                console.print(f"[bold red]Verification warning:[/bold red] {issue}")
            console.print("Migration may be incomplete. Source stores unchanged.")
            raise typer.Exit(1)
        console.print("[green]Verification passed.[/green]")

    # Update config
    try:
        cfg.server.graph_adapter = "ladybug"
        cfg.server.vector_adapter = "ladybug"
        save_config(cfg)
        console.print("\n[green]Config updated — now using LadybugDB as default backend.[/green]")
    finally:
        neo4j.close()


def _migrate_graph(neo4j, target) -> None:
    """Export graph nodes and relationships from Neo4j into LadybugDB."""
    from rich.progress import Progress

    with Progress() as progress, neo4j.driver.session() as session:
        _migrate_core_nodes(session, target, progress)
        _migrate_edges(session, target, progress)
        _migrate_prs_and_policies(session, target, progress)


def _migrate_core_nodes(session, target, progress) -> None:
    """Migrate Repository, File, and CodeBlock nodes."""
    repos = [dict(r["n"]) for r in session.run("MATCH (n:Repository) RETURN n")]
    task = progress.add_task("Repositories", total=len(repos))
    for repo in repos:
        target.create_repo_node(repo.get("id", ""), repo.get("name", ""), repo.get("url", ""))
        if repo.get("last_indexed_commit"):
            target.update_last_indexed_commit(repo["id"], repo["last_indexed_commit"])
        progress.advance(task)

    files = [dict(r["n"]) for r in session.run("MATCH (n:File) RETURN n")]
    task = progress.add_task("Files", total=len(files))
    for f in files:
        target.create_file_node(f.get("repo_id", ""), f.get("path", ""), f.get("qdrant_id", ""))
        progress.advance(task)

    blocks = [dict(r["n"]) for r in session.run("MATCH (n:CodeBlock) RETURN n")]
    task = progress.add_task("CodeBlocks", total=len(blocks))
    for b in blocks:
        target.create_code_node(
            repo_id=b.get("repo_id", ""),
            file_path=b.get("file_path", ""),
            name=b.get("name", ""),
            node_type=b.get("type", ""),
            start_line=b.get("start_line", 0),
            end_line=b.get("end_line", 0),
            qdrant_id=b.get("qdrant_id", ""),
        )
        progress.advance(task)


def _migrate_edges(session, target, progress) -> None:
    """Migrate IMPORTS and CALLS relationships."""
    imports = list(
        session.run("MATCH (f:File)-[:IMPORTS]->(m:Module) RETURN f.repo_id AS rid, f.path AS fp, m.name AS mn")
    )
    task = progress.add_task("Imports", total=len(imports))
    for r in imports:
        target.create_import_relationship(r["rid"], r["fp"], r["mn"])
        progress.advance(task)

    calls = list(
        session.run("MATCH (f:File)-[:CALLS]->(fn:Function) RETURN f.repo_id AS rid, f.path AS fp, fn.name AS fn")
    )
    task = progress.add_task("Calls", total=len(calls))
    for r in calls:
        target.create_call_relationship(r["rid"], r["fp"], r["fn"])
        progress.advance(task)


def _migrate_prs_and_policies(session, target, progress) -> None:
    """Migrate PullRequest and PolicyRule nodes with their relationships."""
    from .server.adapters.ladybug import _make_id

    prs = [dict(r["pr"]) for r in session.run("MATCH (pr:PullRequest) RETURN pr")]
    if prs:
        task = progress.add_task("PullRequests", total=len(prs))
        for pr in prs:
            pr_id = _make_id(str(pr.get("repo_id", "")), str(pr.get("number", "")))
            target._conn.execute(
                "MERGE (pr:PullRequest {id: $id}) "
                "SET pr.number = $num, pr.repo_id = $rid, pr.title = $title, "
                "pr.state = $state, pr.author = $author",
                parameters={
                    "id": pr_id,
                    "num": pr.get("number", 0),
                    "rid": pr.get("repo_id", ""),
                    "title": pr.get("title", ""),
                    "state": pr.get("state", ""),
                    "author": pr.get("author", ""),
                },
            )
            progress.advance(task)

        pr_files = list(
            session.run(
                "MATCH (pr:PullRequest)-[:MODIFIES]->(f:File) RETURN pr.number AS num, pr.repo_id AS rid, f.path AS fp"
            )
        )
        if pr_files:
            task = progress.add_task("PR links", total=len(pr_files))
            for r in pr_files:
                pr_id = _make_id(r["rid"], str(r["num"]))
                file_id = _make_id(r["rid"], r["fp"])
                try:
                    target._conn.execute(
                        "MATCH (pr:PullRequest {id: $pid}), (f:File {id: $fid}) "
                        "MERGE (pr)-[:PullRequest_MODIFIES_File]->(f)",
                        parameters={"pid": pr_id, "fid": file_id},
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: failed to link PR {r['num']} to file: {e}[/yellow]")
                progress.advance(task)

    policies = [dict(r["p"]) for r in session.run("MATCH (p:PolicyRule) RETURN p")]
    if policies:
        task = progress.add_task("Policies", total=len(policies))
        for p in policies:
            target._conn.execute(
                "MERGE (pol:PolicyRule {id: $id}) "
                "SET pol.type = $type, pol.pattern = $pattern, "
                "pol.severity = $severity, pol.message = $message",
                parameters={
                    "id": p.get("id", ""),
                    "type": p.get("type", ""),
                    "pattern": p.get("pattern", ""),
                    "severity": p.get("severity", ""),
                    "message": p.get("message", ""),
                },
            )
            progress.advance(task)


def _migrate_vectors(qdrant_client, collection_name: str, target) -> int:
    """Scroll all vectors from Qdrant (sync client) and write them to LadybugDB."""
    count = 0
    offset = None
    while True:
        results, next_offset = qdrant_client.scroll(
            collection_name=collection_name,
            limit=100,
            offset=offset,
            with_vectors=True,
        )
        if not results:
            break
        for point in results:
            if point.vector and point.payload:
                meta = dict(point.payload)
                text = meta.pop("text", "")
                target._conn.execute(
                    """
                    MERGE (c:CodeBlock {id: $id})
                    SET c.name = $name, c.type = $type, c.file_path = $path,
                        c.repo_id = $repo_id, c.text = $text, c.embedding = $vec
                    """,
                    parameters={
                        "id": str(point.id),
                        "name": meta.get("name", ""),
                        "type": meta.get("type", ""),
                        "path": meta.get("path", ""),
                        "repo_id": meta.get("repo_id", ""),
                        "text": text,
                        "vec": list(point.vector),
                    },
                )
                count += 1
        offset = next_offset
        if offset is None:
            break
    return count


async def _migrate_to_server(verify: bool):
    """Migrate from LadybugDB to Neo4j + Qdrant."""
    from .config import get_config, save_config
    from .stores import resolve_ladybug_path

    cfg = get_config()

    if cfg.server.graph_adapter != "ladybug" or cfg.server.vector_adapter != "ladybug":
        console.print("Not currently using LadybugDB. Nothing to migrate.")
        raise typer.Exit(0)

    # Source: LadybugDB
    from pathlib import Path

    from .server.adapters import LadybugUnifiedStore

    lb_path = resolve_ladybug_path(cfg)
    if not Path(lb_path).exists():
        console.print(f"[bold red]LadybugDB database not found at {lb_path}[/bold red]")
        raise typer.Exit(1)

    source = LadybugUnifiedStore(lb_path, cfg.embeddings.dimension)

    # Target: Neo4j + Qdrant
    try:
        from .server.adapters import Neo4jStore

        neo4j = Neo4jStore(uri=cfg.store.neo4j_uri, user=cfg.store.neo4j_user, password=cfg.store.neo4j_password)

        from qdrant_client import QdrantClient

        if cfg.store.qdrant_url:
            qdrant = QdrantClient(url=cfg.store.qdrant_url, api_key=cfg.store.qdrant_api_key or None)
        else:
            qdrant = QdrantClient(host=cfg.store.qdrant_host, port=cfg.store.qdrant_port)
    except Exception as e:
        console.print(f"[bold red]Cannot connect to target stores:[/bold red] {e}")
        raise typer.Exit(1) from None

    source_stats = await source.get_stats()
    console.print(
        f"\n[bold]Source (LadybugDB):[/bold] {source_stats['node_count']} nodes, {source_stats['edge_count']} edges"
    )

    # Migrate graph
    console.print("\n[bold]Migrating graph to Neo4j...[/bold]")
    _export_ladybug_to_neo4j(source, neo4j)

    # Migrate vectors
    console.print("\n[bold]Migrating vectors to Qdrant...[/bold]")
    vec_count = _export_ladybug_to_qdrant(source, qdrant, cfg.store.qdrant_collection, cfg.embeddings.dimension)
    console.print(f"  Migrated {vec_count} vectors")

    if verify:
        console.print("\n[bold]Verifying...[/bold]")
        target_stats = await neo4j.get_stats()
        console.print(f"  Target: {target_stats['node_count']} nodes, {target_stats['edge_count']} edges")
        if target_stats["node_count"] == 0 and source_stats["node_count"] > 0:
            console.print("[bold red]Verification failed.[/bold red] Source unchanged.")
            raise typer.Exit(1)
        console.print("[green]Verification passed.[/green]")

    try:
        cfg.server.graph_adapter = "neo4j"
        cfg.server.vector_adapter = "qdrant"
        save_config(cfg)
        console.print("\n[green]Config updated — now using Neo4j + Qdrant.[/green]")
    finally:
        neo4j.close()


def _export_ladybug_to_neo4j(source, neo4j) -> None:
    """Export LadybugDB graph data into Neo4j."""
    from rich.progress import Progress

    conn = source._conn
    with Progress() as progress, neo4j.driver.session() as session:
        _export_lb_core_to_neo4j(conn, session, progress)
        _export_lb_extras_to_neo4j(conn, session, progress)


def _export_lb_core_to_neo4j(conn, session, progress) -> None:
    """Export core nodes and edges from LadybugDB to Neo4j."""
    repos = conn.execute("MATCH (r:Repository) RETURN r.id, r.name, r.url, r.last_indexed_commit").get_all()
    task = progress.add_task("Repositories", total=len(repos))
    for r in repos:
        session.run(
            "MERGE (r:Repository {id: $id}) SET r.name = $name, r.url = $url, r.last_indexed_commit = $sha",
            id=r[0],
            name=r[1] or "",
            url=r[2] or "",
            sha=r[3],
        )
        progress.advance(task)

    files = conn.execute("MATCH (f:File) RETURN f.path, f.repo_id").get_all()
    task = progress.add_task("Files", total=len(files))
    for f in files:
        session.run(
            "MATCH (r:Repository {id: $rid}) MERGE (f:File {path: $path, repo_id: $rid}) MERGE (r)-[:CONTAINS]->(f)",
            path=f[0],
            rid=f[1],
        )
        progress.advance(task)

    blocks = conn.execute(
        "MATCH (c:CodeBlock) RETURN c.name, c.type, c.file_path, c.repo_id, c.start_line, c.end_line"
    ).get_all()
    task = progress.add_task("CodeBlocks", total=len(blocks))
    for b in blocks:
        session.run(
            "MATCH (f:File {repo_id: $rid, path: $fp}) "
            "MERGE (c:CodeBlock {name: $name, type: $type, file_path: $fp, repo_id: $rid}) "
            "SET c.start_line = $sl, c.end_line = $el MERGE (f)-[:DEFINES]->(c)",
            name=b[0] or "",
            type=b[1] or "",
            fp=b[2] or "",
            rid=b[3] or "",
            sl=b[4] or 0,
            el=b[5] or 0,
        )
        progress.advance(task)

    imports = conn.execute(
        "MATCH (f:File)-[:File_IMPORTS_Module]->(m:Module) RETURN f.repo_id, f.path, m.name"
    ).get_all()
    task = progress.add_task("Imports", total=len(imports))
    for r in imports:
        session.run(
            "MATCH (f:File {repo_id: $rid, path: $fp}) MERGE (m:Module {name: $mn, repo_id: $rid}) "
            "MERGE (f)-[:IMPORTS]->(m)",
            rid=r[0],
            fp=r[1],
            mn=r[2],
        )
        progress.advance(task)

    calls = conn.execute(
        "MATCH (f:File)-[:File_CALLS_Function]->(fn:Function) RETURN f.repo_id, f.path, fn.name"
    ).get_all()
    task = progress.add_task("Calls", total=len(calls))
    for r in calls:
        session.run(
            "MATCH (f:File {repo_id: $rid, path: $fp}) MERGE (fn:Function {name: $fn, repo_id: $rid}) "
            "MERGE (f)-[:CALLS]->(fn)",
            rid=r[0],
            fp=r[1],
            fn=r[2],
        )
        progress.advance(task)


def _export_lb_extras_to_neo4j(conn, session, progress) -> None:
    """Export PullRequests and PolicyRules from LadybugDB to Neo4j."""
    _export_lb_prs_to_neo4j(conn, session, progress)
    _export_lb_policies_to_neo4j(conn, session, progress)


def _export_lb_prs_to_neo4j(conn, session, progress) -> None:
    """Export PullRequest nodes and MODIFIES edges from LadybugDB to Neo4j."""
    prs = conn.execute(
        "MATCH (pr:PullRequest) RETURN pr.number, pr.repo_id, pr.title, pr.url, pr.state, pr.author"
    ).get_all()
    if not prs:
        return
    task = progress.add_task("PullRequests", total=len(prs))
    for pr in prs:
        session.run(
            "MERGE (pr:PullRequest {number: $num, repo_id: $rid}) "
            "SET pr.title = $title, pr.url = $url, pr.state = $state, pr.author = $author",
            num=pr[0],
            rid=pr[1] or "",
            title=pr[2] or "",
            url=pr[3] or "",
            state=pr[4] or "",
            author=pr[5] or "",
        )
        progress.advance(task)

    pr_files = conn.execute(
        "MATCH (pr:PullRequest)-[:PullRequest_MODIFIES_File]->(f:File) RETURN pr.number, pr.repo_id, f.path"
    ).get_all()
    if not pr_files:
        return
    task = progress.add_task("PR links", total=len(pr_files))
    for r in pr_files:
        session.run(
            "MATCH (pr:PullRequest {number: $num, repo_id: $rid}), "
            "(f:File {path: $fp, repo_id: $rid}) MERGE (pr)-[:MODIFIES]->(f)",
            num=r[0],
            rid=r[1] or "",
            fp=r[2] or "",
        )
        progress.advance(task)


def _export_lb_policies_to_neo4j(conn, session, progress) -> None:
    """Export PolicyRule nodes from LadybugDB to Neo4j."""
    policies = conn.execute("MATCH (p:PolicyRule) RETURN p.id, p.type, p.pattern, p.severity, p.message").get_all()
    if not policies:
        return
    task = progress.add_task("Policies", total=len(policies))
    for p in policies:
        session.run(
            "MERGE (p:PolicyRule {id: $id}) "
            "SET p.type = $type, p.pattern = $pattern, p.severity = $severity, p.message = $message",
            id=p[0],
            type=p[1] or "",
            pattern=p[2] or "",
            severity=p[3] or "",
            message=p[4] or "",
        )
        progress.advance(task)


def _export_ladybug_to_qdrant(source, qdrant, collection_name: str, dimension: int) -> int:
    """Export LadybugDB CodeBlock embeddings into Qdrant."""
    import uuid

    from qdrant_client.http import models

    # Ensure collection exists
    try:
        qdrant.get_collection(collection_name)
    except Exception:
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )

    conn = source._conn
    rows = conn.execute(
        "MATCH (c:CodeBlock) WHERE c.embedding IS NOT NULL "
        "RETURN c.id, c.name, c.type, c.file_path, c.repo_id, c.text, c.embedding"
    ).get_all()

    points = []
    for row in rows:
        cid, name, ctype, path, repo_id, text, embedding = row
        if not embedding:
            continue
        # Preserve existing ID if it's UUID-compatible, otherwise derive one
        raw_id = cid or f"{repo_id}:{path}:{name}"
        try:
            point_id = str(uuid.UUID(raw_id))
        except ValueError:
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id))
        points.append(
            models.PointStruct(
                id=point_id,
                vector=list(embedding),
                payload={
                    "text": text or "",
                    "name": name or "",
                    "type": ctype or "",
                    "path": path or "",
                    "repo_id": repo_id or "",
                },
            )
        )

    if points:
        # Batch upsert in chunks of 100
        for i in range(0, len(points), 100):
            qdrant.upsert(collection_name=collection_name, points=points[i : i + 100])

    return len(points)


if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
