# MCP Tools

Clewso exposes code intelligence as MCP (Model Context Protocol) tools that AI agents can call directly.

## Available tools

### `search_codebase`

Semantic search across indexed code. Returns ranked results combining vector similarity and graph context.

### `explore_module`

Analyze a module's dependencies, exports, and API surface.

### `verify_concept`

Quick check whether a library, pattern, or concept exists in the indexed codebase before deep analysis.

### `list_repos`

List all indexed repositories.

## Running the MCP server

```bash
docker compose up -d  # starts API + backing services
```

The MCP server connects to the Clewso API and exposes tools over the MCP protocol. Configure your editor with `clewso setup-editor` to point at the running server.
