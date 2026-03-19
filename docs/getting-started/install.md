# Installation

## Requirements

- Python 3.11+
- Docker (for Neo4j and Qdrant)

## Install the CLI

```bash
# pip
pip install clewso

# uv
uv tool install clewso

# pipx
pipx install clewso
```

## Start the backing services

```bash
docker compose up -d
```

This starts Neo4j (graph store) and Qdrant (vector store) locally.

## Verify

```bash
clewso --help
```
