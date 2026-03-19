# Graph API

## `POST /v1/graph/traverse`

Traverse the code dependency graph from a starting node.

### Request

```json
{
  "start_node_id": "node-abc123",
  "relationship_types": ["IMPORTS", "CALLS"],
  "depth": 2
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `start_node_id` | string | yes | Node ID to start traversal from |
| `relationship_types` | string[] | no | Edge types to follow |
| `depth` | int | no | Max hops (default: 2) |

### Response

```json
{
  "nodes": [
    {
      "id": "node-abc123",
      "metadata": {
        "path": "src/auth/middleware.py",
        "type": "module"
      }
    }
  ],
  "edges": [
    {
      "source": "node-def456",
      "target": "node-abc123",
      "type": "IMPORTS"
    }
  ]
}
```
