# Packages

Clewso is a monorepo with three published packages. All packages are versioned together.

## `clewso`

The user-facing CLI. Install this to index repos, run reviews, and configure editors.

```bash
pip install clewso
```

**Depends on:** `clewso-ingestion`

## `clewso-ingestion`

The indexing pipeline. Parses source files with tree-sitter, extracts dependency graphs, generates embeddings, and writes to Neo4j + Qdrant.

```bash
pip install clewso-ingestion
```

**Depends on:** `clewso-core`

## `clewso-core`

Shared types, schemas, and the embedding client used by both the ingestion pipeline and the API.

```bash
pip install clewso-core
```

## Internal packages (not published)

- **`context-engine-api`** — FastAPI service exposing search, graph traversal, and policy endpoints
- **`context-mcp-server`** — MCP server that proxies AI agent tool calls to the API
