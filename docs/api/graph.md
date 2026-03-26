# Graph API

## `POST /v1/graph/traverse`

Traverse the code dependency graph from a starting node.

### Request

```json
{
  "start_node_id": "node-abc123",
  "relationship_types": ["IMPORTS", "CALLS"],
  "depth": 2,
  "repo_id": "my-org/my-repo"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `start_node_id` | string | required | Node ID to start traversal from |
| `relationship_types` | string[] | `["IMPORTS", "CALLS", "CONTAINS", "DEFINES"]` | Edge types to follow |
| `depth` | int | `2` | Max hops (1-3) |
| `repo_id` | string | — | Scope traversal to a repository |

### Response

```json
{
  "nodes": [
    {
      "id": "123",
      "label": "File",
      "properties": {
        "path": "src/auth/middleware.py",
        "repo_id": "my-org/my-repo"
      }
    }
  ],
  "edges": [
    {
      "id": "456",
      "source": "789",
      "target": "123",
      "type": "IMPORTS",
      "properties": {}
    }
  ]
}
```

## `GET /v1/graph/file/{file_path}/pull_requests`

List pull requests that touched a file.

## `GET /v1/graph/pull_request/{pr_number}/impact`

Analyze the impact radius of a pull request.
