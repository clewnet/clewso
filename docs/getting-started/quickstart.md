# Quick Start

## Index your repo

```bash
clewso index ./path/to/your/repo
```

This parses your code, extracts the dependency graph, generates embeddings, and stores everything in Neo4j + Qdrant.

## Set up your editor

```bash
clewso setup-editor
```

Auto-detects which AI editors you use and configures them with Clewso MCP tool directives. Supports: Claude Code, Cursor, Copilot, Gemini, Windsurf, Antigravity.

## Run a smart review

```bash
# Review staged changes
clewso review --staged

# Review a PR
clewso review --pr

# Dry-run in CI (exits 1 on blocking violations)
clewso review --staged --dry-run --output json
```
