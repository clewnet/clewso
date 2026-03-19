# Clewso

**The Open Source Context Server for AI Agents.**

Clewso indexes your codebase and gives AI agents structured, navigable context by combining **vector search** (Qdrant) with **graph traversal** (Neo4j). It solves the "Lost in the Middle" problem so your agents actually understand your code.

## Features

- **Hybrid search** — semantic vector search + code graph traversal in one query
- **MCP tools** — drop-in tools for Claude Code, Cursor, Copilot, and more
- **Smart review** — context-aware PR review powered by impact graph analysis
- **Local-first** — runs on your machine, indexes your repo, 100% privacy
- **Three packages** — install what you need:
    - `clewso` — CLI with review, index, and editor setup commands
    - `clewso-ingestion` — repo indexing pipeline
    - `clewso-core` — shared types and embedding client

## Quick start

```bash
pip install clewso
docker compose up -d   # Neo4j + Qdrant
clewso index ./my-repo
clewso setup-editor    # auto-detect and configure your editor
```

See the [installation guide](getting-started/install.md) for full setup instructions.
