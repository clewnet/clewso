# Packages

Clewso is a monorepo with three published packages. All packages are versioned together.

## `clewso`

The user-facing CLI and optional API/MCP servers. Install this to index repos, run reviews, and configure editors.

```bash
pip install clewso          # CLI only
pip install "clewso[server]" # CLI + API server
pip install "clewso[mcp]"    # CLI + MCP server
pip install "clewso[all]"    # everything
```

**Depends on:** `clewso-ingestion`, `neo4j`, `typer`, `rich`, `httpx`, `tenacity`

The API server (`clewso serve`) and MCP server (`clewso mcp`) are optional extras — the CLI works standalone for indexing and review.

## `clewso-ingestion`

The indexing pipeline. Parses source files with tree-sitter, extracts dependency graphs, generates embeddings, and writes to Neo4j + Qdrant. Features pipelined parsing and concurrent embedding requests.

```bash
pip install clewso-ingestion
```

**Depends on:** `clewso-core`, `qdrant-client`, `neo4j`, `tree-sitter`, `tree-sitter-language-pack`

## `clewso-core`

Shared types, schemas, and the embedding client used by both the ingestion pipeline and the API.

```bash
pip install clewso-core
```
