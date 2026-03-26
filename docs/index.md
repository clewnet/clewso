# Clewso

**The Open Source Context Server for AI Agents.**

Clewso indexes your codebase and gives AI agents structured, navigable context by combining **vector search** (Qdrant) with **graph traversal** (Neo4j). It solves the "Lost in the Middle" problem so your agents actually understand your code.

## Features

- **Hybrid search** — semantic vector search + code graph traversal in one query
- **MCP tools** — drop-in tools for Claude Code, Cursor, Copilot, and more
- **Smart review** — graph-based impact analysis with same-diff awareness, deletion coherence, and LLM reasoning
- **Local or cloud** — runs locally with Docker, or connects to Qdrant Cloud + Neo4j Aura
- **Three packages** — install what you need:
    - `clewso` — CLI with review, index, serve, and editor setup commands
    - `clewso-ingestion` — repo indexing pipeline with concurrent embeddings
    - `clewso-core` — shared types and embedding client

## Quick start

```bash
uv tool install clewso       # or: pip install clewso
clewso init                   # configure stores
clewso index ./my-repo        # index your codebase
clewso setup-editor           # auto-detect and configure your editor
clewso review --staged        # graph-aware code review
```

See the [installation guide](getting-started/install.md) for full setup instructions.
