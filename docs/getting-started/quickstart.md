# Quick Start

## 1. Configure (first time only)

```bash
clewso init
```

Sets up your embedding provider, Qdrant, and Neo4j connections.

## 2. Index your repo

```bash
clewso index ./path/to/your/repo
```

This parses your code, extracts the dependency graph, generates embeddings, and stores everything in Neo4j + Qdrant. The repo ID is automatically derived from the git remote (e.g. `owner/repo`).

```bash
# Explicit repo ID
clewso index . --repo-id myorg/myrepo

# Incremental (only changed files since last index)
clewso index . --incremental
```

## 3. Set up your editor

```bash
clewso setup-editor
```

Auto-detects which AI editors you use and configures them with Clewso MCP tool directives. Supports: Claude Code, Cursor, Copilot, Gemini, Windsurf, Antigravity.

```bash
# Specific editor
clewso setup-editor cursor

# Force overwrite existing config
clewso setup-editor --force
```

## 4. Run a smart review

```bash
# Review unstaged changes
clewso review

# Review staged changes
clewso review --staged

# Review a PR (diff against origin/main)
clewso review --pr

# Dry-run in CI (exits 1 on blocking policy violations)
clewso review --staged --dry-run --output json
```

The review uses graph-based impact analysis: it queries the dependency graph to find downstream consumers of each changed file, checks whether those consumers are also updated in the same diff, and uses an LLM to assess breaking-change risk.
