# Smart Review

Clewso's smart review analyzes code changes using the indexed dependency graph to find downstream breakage risks.

## How it works

1. **Parse diff** — extracts changed files from `git diff`
2. **Impact graph** — queries Neo4j for reverse dependencies (who imports/calls the changed file)
3. **Context fetch** — reads source of impacted files within a token budget
4. **LLM analysis** — sends diff + context to an LLM for risk assessment
5. **Policy check** — validates against server-side policies (banned imports, protected paths)

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
| `CLEW_API_URL` | `http://localhost:8000/v1` | API base URL |
| `CLEW_API_KEY` | — | API key (for platform mode) |
| `OPENAI_API_KEY` | — | Required for LLM analysis |
| `OPENAI_MODEL` | `gpt-4-turbo-preview` | LLM model to use |
