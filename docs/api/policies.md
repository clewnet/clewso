# Policies API

## `GET /v1/policies`

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
      "message": "Use of eval() is prohibited"
    },
    {
      "id": "protect-auth",
      "type": "protected_write",
      "pattern": "src/auth/**",
      "severity": "warn",
      "message": "Changes to auth require security review"
    }
  ]
}
```

### Policy types

| Type | Description |
|---|---|
| `banned_import` | Blocks diffs containing matching import statements |
| `protected_write` | Warns/blocks when matching file paths are modified |
| `unguarded_path` | Warns/blocks when matching file paths are modified without guard |

### Severity levels

| Severity | Effect |
|---|---|
| `block` | `clewso review --dry-run` exits with code 1 |
| `warn` | Reported but does not block |
| `audit` | Logged for compliance tracking |
