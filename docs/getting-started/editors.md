# Editor Setup

Clewso can configure AI coding assistants to use its MCP tools for codebase exploration.

## Auto-detect

```bash
clewso setup-editor
```

Scans your project for editor config files and configures all detected editors.

## Specific editor

```bash
clewso setup-editor claude-code
clewso setup-editor cursor
clewso setup-editor copilot
clewso setup-editor gemini
clewso setup-editor windsurf
clewso setup-editor antigravity
clewso setup-editor all
```

## What it does

Adds a directive block to your editor's instruction file telling the AI to prefer Clewso MCP tools (`search_codebase`, `explore_module`, `verify_concept`, `list_repos`) over raw file reads when exploring unfamiliar code.
