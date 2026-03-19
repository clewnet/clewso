# Search API

## `POST /v1/search`

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
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Natural language search query |
| `limit` | int | no | Max results (default: 10) |
| `repo` | string | no | Filter to a specific repository |
| `filters` | object | no | Additional filters (path, type) |

### Response

```json
{
  "results": [
    {
      "id": "node-abc123",
      "score": 0.92,
      "metadata": {
        "path": "src/auth/middleware.py",
        "repo": "my-org/my-repo",
        "type": "function",
        "name": "verify_token"
      },
      "content": "def verify_token(request): ..."
    }
  ]
}
```
