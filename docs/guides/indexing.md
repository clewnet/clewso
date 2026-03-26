# Indexing a Repo

## Full index

```bash
clewso index ./path/to/repo
```

Parses all supported files, extracts the code graph (imports, calls, definitions), generates embeddings, and stores them in Neo4j + Qdrant.

At the end of indexing, a summary shows actual store counts:

```
[Finalization]   Qdrant:  1067 points (repo), 1067 total
[Finalization]   Neo4j:   199 files, 868 code blocks, 67 modules, 1329 functions, 3202 relationships
```

## Incremental index

```bash
clewso index ./path/to/repo --incremental
```

Only indexes files changed since the last indexed commit. Much faster for large repos.

## Custom repo ID

```bash
clewso index ./path/to/repo --repo-id my-org/my-repo
```

By default, the repo ID is derived from the git remote URL (e.g. `owner/repo`). Falls back to the directory name if no remote is found.

## Configuration

Indexing reads connection settings from the unified config chain (highest priority first):

1. `CLEWSO_*` environment variables (e.g. `CLEWSO_STORE_QDRANT_URL`)
2. Legacy environment variables (e.g. `QDRANT_API_ENDPOINT`)
3. Project `.env` file
4. `~/.config/clewso/config.toml`
5. Built-in defaults

### Store environment variables

| Variable | Config key | Description |
|---|---|---|
| `QDRANT_API_ENDPOINT` | `store.qdrant_url` | Qdrant Cloud URL |
| `QDRANT_API_TOKEN` | `store.qdrant_api_key` | Qdrant Cloud API key |
| `QDRANT_HOST` | `store.qdrant_host` | Qdrant host (default: `localhost`) |
| `QDRANT_PORT` | `store.qdrant_port` | Qdrant port (default: `6335`) |
| `NEO4J_URI` | `store.neo4j_uri` | Neo4j connection URI |
| `NEO4J_USER` | `store.neo4j_user` | Neo4j username |
| `NEO4J_PASSWORD` | `store.neo4j_password` | Neo4j password |
| `OPENAI_API_KEY` | `embeddings.openai_api_key` | OpenAI API key for embeddings |

### Other environment variables

| Variable | Default | Description |
|---|---|---|
| `CLEW_WRITE_MODE` | `open` | Set to `ci-only` for CI environments |
| `CLEW_CI_TOKEN` | — | Required when `CLEW_WRITE_MODE=ci-only` |

## Supported languages

Clewso uses tree-sitter for AST parsing. Supported languages include Python, JavaScript, TypeScript, Go, Rust, C/C++, Java, C#, Ruby, PHP, Swift, Kotlin, Scala, Lua, Elixir, Haskell, OCaml, Bash, Zig, and Dart. Data formats (HTML, CSS, YAML, TOML, JSON, SQL) are indexed for search but don't produce graph edges.
