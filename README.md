<p align="center">
<pre>
    ,;;;,.
   ;;O  O;;
   `;    ;'
    `;;;;'
   ~~/  \~~
  ~/    _ \~
 ~/   (.) \~
~/ ~~~~~~~~\~
</pre>
</p>

<h1 align="center">Clewso 🧶👀</h1>
<h3 align="center">The Open Source Context Server for AI Agents.</h3>

<p align="center">
  <strong>Runs locally. Indexes your repo. 100% Privacy.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License"></a>
  <a href="https://github.com/clewnet/clewso/actions/workflows/publish.yml"><img src="https://github.com/clewnet/clewso/actions/workflows/publish.yml/badge.svg" alt="Publish"></a>
  <a href="https://pypi.org/project/clewso/"><img src="https://img.shields.io/pypi/v/clewso.svg" alt="PyPI"></a>
  <a href="https://clewso.sh"><img src="https://img.shields.io/badge/docs-clewso.sh-blue" alt="Docs"></a>
</p>

---

Clewso indexes your codebase and gives AI agents **structured, navigable context** by combining **vector search** (Qdrant) with **graph traversal** (Neo4j).

## Quick Start

```bash
uv tool install clewso       # or: pip install clewso
clewso init                   # configure stores (local Docker or cloud)
clewso index ./my-repo        # index your codebase
clewso setup-editor           # configure your AI editor
clewso review --staged        # graph-aware code review
```

## Features

- **Hybrid search** — semantic vectors + code graph in one query
- **MCP tools** — drop-in for Claude Code, Cursor, Copilot, Gemini, Windsurf
- **Smart review** — context-aware PR review with impact graph analysis
- **Local-first** — your machine, your data, no cloud dependency

## Packages

| Package | Description |
|---|---|
| [`clewso`](https://pypi.org/project/clewso/) | CLI — index, review, editor setup |
| [`clewso-ingestion`](https://pypi.org/project/clewso-ingestion/) | Repo indexing pipeline |
| [`clewso-core`](https://pypi.org/project/clewso-core/) | Shared types and embedding client |

## Documentation

Full docs at **[clewso.sh](https://clewso.sh)**.

## License

[AGPL-3.0](LICENSE)
