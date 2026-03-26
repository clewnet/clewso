# Search API

## `POST /v1/search/`

Hybrid vector + graph search across indexed code.

### Request

```json
{
  "query": "authentication middleware",
  "limit": 10,
  "repo": "my-org/my-repo",
  "filters": {
    "path": "src/auth",
    "type": "function"
  },
  "exclude_tests": true,
  "rerank": false,
  "graph_boost": true
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Natural language search query |
| `limit` | int | `10` | Max results |
| `repo` | string | — | Filter to a specific repository |
| `filters` | object | — | Additional filters (`path`, `path_contains`, `type`) |
| `exclude_tests` | bool | `true` | Filter out test files |
| `rerank` | bool | `false` | Enable cross-encoder reranking |
| `graph_boost` | bool | `true` | Boost scores using graph co-occurrence |

### Response

Returns a flat list of results sorted by score:

```json
[
  {
    "id": "a1b2c3d4-...",
    "score": 0.92,
    "content": "def verify_token(request): ...",
    "metadata": {
      "path": "src/auth/middleware.py",
      "repo_id": "my-org/my-repo",
      "type": "function",
      "name": "verify_token"
    }
  }
]
```
