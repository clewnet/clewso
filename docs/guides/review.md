# Smart Review

Clewso's smart review analyzes code changes using the indexed dependency graph to find downstream breakage risks.

## How it works

1. **Parse diff** — extracts changed files from `git diff` (lockfiles are skipped automatically)
2. **Impact graph** — queries Neo4j directly for reverse dependencies: files that import modules from, or call functions defined in, the changed file
3. **Same-diff detection** — marks downstream consumers that are also modified or deleted in this diff
4. **Package context** — checks workspace membership and greps for removed public symbols to assess external-consumer risk
5. **Context fetch** — reads source of impacted files (falls back to `git show HEAD` for deleted files)
6. **LLM analysis** — sends diff + consumer list + context + analysis notes to an LLM for risk assessment
7. **Policy check** — validates against server-side policies (banned imports, protected paths)

## Risk levels

- **HIGH** — definite breaking change (missing symbol, deleted file with live consumers)
- **MEDIUM** — likely breaking change (signature mismatch, type change)
- **LOW** — possible issue (style change, deprecation)
- **SAFE** — no breaking changes detected

The review automatically reduces risk when:

- A downstream consumer is **co-changed** in the same diff and the change addresses the breakage
- A file and **all its consumers are deleted** together (coordinated teardown)
- A removed public API has **zero remaining references** in the codebase
- The crate/package is **workspace-internal** with no external consumers

## Usage

```bash
# Review unstaged changes
clewso review

# Review staged changes
clewso review --staged

# Review a PR (diff against origin/main)
clewso review --pr

# Output formats
clewso review --output markdown   # default
clewso review --output rich       # terminal table
clewso review --output json       # machine-readable
```

## CI integration

```bash
clewso review --staged --dry-run --output json
```

Exits with code 1 if blocking policy violations are found. Use in pre-commit hooks or CI pipelines.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for LLM analysis |
| `OPENAI_MODEL` | `gpt-4-turbo-preview` | LLM model for risk assessment |
| `OPENAI_API_BASE` | `https://api.openai.com/v1` | Custom OpenAI-compatible endpoint |
| `CLEW_API_KEY` | — | API key (only for platform mode policy checks) |

Neo4j and Qdrant connections are read from `~/.config/clewso/config.toml` or the standard store environment variables (see [Indexing](indexing.md#configuration)).
