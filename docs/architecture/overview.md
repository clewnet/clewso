# Architecture Overview

Clewso is a hybrid vector + graph code search engine designed to give AI agents structured context about a codebase.

## Components

```
clewso (CLI)
  ├── clewso index         → clewso-ingestion → Neo4j + Qdrant
  ├── clewso review        → Neo4j (direct) + LLM
  ├── clewso serve         → starts FastAPI server
  ├── clewso mcp           → starts MCP tool server
  ├── clewso init          → interactive config setup
  ├── clewso config        → show/set config values
  └── clewso setup-editor  → configure AI editors

API server (clewso serve)
  ├── /v1/search      → Qdrant (vector) + Neo4j (graph boost)
  ├── /v1/graph/*     → Neo4j traversal + PR impact
  ├── /v1/stats       → repository statistics
  ├── /v1/policies    → policy CRUD
  └── /health         → health check

MCP server (clewso mcp)
  └── proxies search/graph/explore to API server
```

## Data flow

1. **Ingestion** — `clewso index` parses source files with tree-sitter, extracts a dependency graph (imports, calls, definitions), generates embeddings, and stores everything in Neo4j (graph) and Qdrant (vectors). Parsing and processing are pipelined via async generators for concurrent embedding requests.

2. **Search** — queries combine vector similarity from Qdrant with graph-boosted reranking from Neo4j. Files that are more connected in the dependency graph rank higher.

3. **Review** — `clewso review` queries Neo4j directly (not through the API) for reverse dependencies of each changed file. It detects co-changed and co-deleted consumers in the same diff, gathers package context (workspace membership, symbol grep), and sends everything to an LLM for breaking-change assessment.

## Configuration

All components read from a unified config chain:

1. `CLEWSO_*` env vars (highest priority)
2. Legacy env vars (e.g. `QDRANT_HOST`, `NEO4J_URI`)
3. Project `.env` file
4. `~/.config/clewso/config.toml`
5. Built-in defaults

Run `clewso init` for interactive setup or `clewso config show` to inspect resolved values.
