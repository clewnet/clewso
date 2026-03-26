# Policies API

## `GET /v1/policies/`

Fetch active policy rules for code review enforcement.

### Response

```json
{
  "policies": [
    {
      "id": "no-eval",
      "type": "banned_import",
      "pattern": "eval",
      "severity": "block",
      "message": "Use of eval() is prohibited",
      "precept_id": null
    }
  ]
}
```

## `POST /v1/policies/`

Create a new policy rule.

### Request

```json
{
  "type": "banned_import",
  "pattern": "eval",
  "severity": "block",
  "message": "Use of eval() is prohibited"
}
```

## `GET /v1/policies/export`

Export all policies as a flat list (for caching in hooks/CI).

## `DELETE /v1/policies/{policy_id}`

Delete a policy by ID.

---

## Policy types

| Type | Description |
|---|---|
| `banned_import` | Blocks diffs containing matching import statements |
| `protected_write` | Warns/blocks when matching file paths are modified |
| `unguarded_path` | Warns/blocks when matching file paths are modified without guard |

## Severity levels

| Severity | Effect |
|---|---|
| `block` | `clewso review --dry-run` exits with code 1 |
| `warn` | Reported but does not block |
| `audit` | Logged for compliance tracking |
