# Installation

## Requirements

- Python 3.11+
- Docker (for local Neo4j and Qdrant) or cloud-hosted instances

## Install the CLI

```bash
# uv (recommended for global CLI)
uv tool install clewso

# pip
pip install clewso

# pipx
pipx install clewso
```

### Optional extras

```bash
# API server (for clewso serve)
pip install "clewso[server]"

# MCP tool server (for clewso mcp)
pip install "clewso[mcp]"

# Everything
pip install "clewso[all]"
```

## Start the backing services

### Option A: Local (Docker)

```bash
docker compose up -d
```

This starts Neo4j (graph store), Qdrant (vector store), and the API server.

### Option B: Cloud

Clewso supports Qdrant Cloud and Neo4j Aura. Run `clewso init` to configure:

```bash
clewso init
```

This interactively configures your embedding provider, Qdrant connection
(local host/port or cloud URL + API key), and Neo4j connection. Settings
are saved to `~/.config/clewso/config.toml`.

If you already have a config file, `clewso init` will detect it and
suggest using `clewso config set <key> <value>` for individual changes,
or `clewso init --force` to reconfigure.

## Verify

```bash
clewso --help
```
