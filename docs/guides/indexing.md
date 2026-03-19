# Indexing a Repo

## Full index

```bash
clewso index ./path/to/repo
```

Parses all supported files, extracts the code graph (imports, calls, definitions), generates embeddings, and stores them in Neo4j + Qdrant.

## Incremental index

```bash
clewso index ./path/to/repo --incremental
```

Only indexes files changed since the last indexed commit. Much faster for large repos.

## Custom repo ID

```bash
clewso index ./path/to/repo --repo-id my-org/my-repo
```

By default, the repo ID is auto-generated from the directory name.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CLEW_API_URL` | `http://localhost:8000/v1` | API base URL |
| `CLEW_WRITE_MODE` | `open` | Set to `ci-only` for CI environments |
| `CLEW_CI_TOKEN` | — | Required when `CLEW_WRITE_MODE=ci-only` |
