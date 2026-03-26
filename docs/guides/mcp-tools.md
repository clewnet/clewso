# MCP Tools

Clewso exposes code intelligence as MCP (Model Context Protocol) tools that AI agents can call directly.

## Running the MCP server

```bash
# Install with MCP extras
pip install "clewso[mcp]"

# Start the MCP server
clewso mcp
```

The MCP server connects to the Clewso API and exposes tools over the MCP protocol. Configure your editor with `clewso setup-editor` to point at the running server.

!!! note
    The MCP server requires a running Clewso API server (`clewso serve`) or cloud-hosted backing services.

## Available tools

### `search_codebase`

Semantic search across indexed code. Returns ranked results combining vector similarity and graph context.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Natural language search query |
| `limit` | int | 5 | Maximum results |
| `repo_id` | string | — | Filter to a specific repository |

### `explore_module`

Analyze a module's dependencies, exports, and API surface.

| Parameter | Type | Description |
|---|---|---|
| `path` | string | File path to explore |
| `repo_id` | string | Repository to search in |

### `verify_concept`

Quick check whether a library, pattern, or concept exists in the indexed codebase before deep analysis.

| Parameter | Type | Description |
|---|---|---|
| `concept` | string | Concept to search for |

### `list_repos`

List all indexed repositories. No parameters.
