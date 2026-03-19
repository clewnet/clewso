# Architecture Overview

Clewso is a hybrid vector + graph code search engine designed to give AI agents structured context about a codebase.

## Components

```
clewso (CLI)
  ├── clewso index    → clewso-ingestion → Neo4j + Qdrant
  ├── clewso review   → Clewso API → LLM
  └── clewso setup-editor

clewso-api (FastAPI)
  ├── /v1/search      → Qdrant (vector) + Neo4j (graph boost)
  ├── /v1/graph/*     → Neo4j
  └── /v1/policies    → Neo4j

clewso-mcp (MCP Server)
  └── proxies search/graph/explore to clewso-api
```

## Data flow

1. **Ingestion** — `clewso index` parses source files with tree-sitter, extracts a dependency graph (imports, calls, definitions), generates embeddings, and stores everything in Neo4j (graph) and Qdrant (vectors).

2. **Search** — queries combine vector similarity from Qdrant with graph-boosted reranking from Neo4j. Files that are more connected in the dependency graph rank higher.

3. **Review** — diffs are analyzed by traversing reverse dependencies in the graph, fetching source context, and sending it to an LLM for breaking-change assessment.
