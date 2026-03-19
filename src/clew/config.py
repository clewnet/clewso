"""
Unified configuration for Clewso.

Resolution order (highest priority wins):
  1. Environment variables (CLEWSO_* prefix, plus legacy names)
  2. Project .env file in cwd
  3. User config file (~/.config/clewso/config.toml)
  4. Built-in defaults
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "clewso"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class APIConfig:
    """Connection to the Clewso API server."""

    url: str = "http://localhost:8000"
    key: str = ""
    timeout: float = 30.0


@dataclass
class EmbeddingsConfig:
    """Embedding provider configuration."""

    provider: str = "openai"  # openai | ollama
    openai_api_key: str = ""
    openai_model: str = "text-embedding-3-large"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_model: str = "nomic-embed-text"
    ollama_url: str = "http://localhost:11434"
    ollama_timeout: float = 10.0
    dimension: int = 1536


@dataclass
class StoreConfig:
    """Backing store connections (Qdrant, Neo4j, Postgres)."""

    qdrant_host: str = "localhost"
    qdrant_port: int = 6335
    qdrant_collection: str = "codebase"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    postgres_uri: str = ""


@dataclass
class ServerConfig:
    """API server runtime settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    vector_adapter: str = "qdrant"  # qdrant | pgvector
    graph_adapter: str = "neo4j"  # neo4j | noop
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    graph_boost_weight: float = 0.05


@dataclass
class ReviewConfig:
    """Smart review / LLM settings."""

    model: str = "gpt-4-turbo-preview"


@dataclass
class CIConfig:
    """CI / write-mode settings."""

    write_mode: str = "open"  # open | ci-only
    ci_token: str = ""


@dataclass
class ClewsoConfig:
    """Top-level configuration container."""

    api: APIConfig = field(default_factory=APIConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    ci: CIConfig = field(default_factory=CIConfig)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser. No dependency required."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        env[key] = value
    return env


def _load_toml(path: Path) -> dict[str, Any]:
    """Load TOML config file."""
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


# Legacy env var name → (section, field) mapping.
# These are read as fallbacks so existing setups keep working.
_LEGACY_ENV_MAP: dict[str, tuple[str, str]] = {
    "CLEW_API_URL": ("api", "url"),
    "CLEW_API_KEY": ("api", "key"),
    "CLEW_API_TIMEOUT": ("api", "timeout"),
    "CONTEXT_ENGINE_API_URL": ("api", "url"),
    "OPENAI_API_KEY": ("embeddings", "openai_api_key"),
    "OPENAI_API_BASE": ("embeddings", "openai_base_url"),
    "OPENAI_EMBEDDING_MODEL": ("embeddings", "openai_model"),
    "OPENAI_MODEL": ("review", "model"),
    "OLLAMA_BASE_URL": ("embeddings", "ollama_url"),
    "OLLAMA_API_KEY": ("embeddings", "openai_api_key"),  # ollama uses same field
    "OLLAMA_EMBEDDING_MODEL": ("embeddings", "ollama_model"),
    "NEO4J_URI": ("store", "neo4j_uri"),
    "NEO4J_USER": ("store", "neo4j_user"),
    "NEO4J_PASSWORD": ("store", "neo4j_password"),
    "QDRANT_HOST": ("store", "qdrant_host"),
    "QDRANT_PORT": ("store", "qdrant_port"),
    "POSTGRES_URI": ("store", "postgres_uri"),
    "CLEW_WRITE_MODE": ("ci", "write_mode"),
    "CLEW_CI_TOKEN": ("ci", "ci_token"),
    "CLEW_VECTOR_ADAPTER": ("server", "vector_adapter"),
    "CLEW_GRAPH_ADAPTER": ("server", "graph_adapter"),
    "CLEW_RERANK_ENABLED": ("server", "rerank_enabled"),
    "CLEW_RERANK_MODEL": ("server", "rerank_model"),
    "CLEW_GRAPH_BOOST_WEIGHT": ("server", "graph_boost_weight"),
}

# Section name → dataclass type mapping
_SECTION_TYPES: dict[str, type] = {
    "api": APIConfig,
    "embeddings": EmbeddingsConfig,
    "store": StoreConfig,
    "server": ServerConfig,
    "review": ReviewConfig,
    "ci": CIConfig,
}


def _coerce(value: str, current_value: Any) -> Any:
    """Coerce a string env var to match the type of the current field value."""
    if isinstance(current_value, bool):
        return value.lower() in ("true", "1", "yes")
    if isinstance(current_value, int):
        return int(value)
    if isinstance(current_value, float):
        return float(value)
    return value


def _apply_dict(cfg: ClewsoConfig, data: dict[str, Any]) -> None:
    """Apply a nested dict (from TOML) onto the config dataclass."""
    for section_name, section_data in data.items():
        if not isinstance(section_data, dict):
            continue
        section = getattr(cfg, section_name, None)
        if section is None:
            continue
        for key, value in section_data.items():
            if hasattr(section, key):
                setattr(section, key, value)


def _apply_env(cfg: ClewsoConfig, environ: dict[str, str]) -> None:
    """Apply environment variables onto the config.

    Supports two forms:
      - CLEWSO_<SECTION>_<FIELD> (canonical)
      - Legacy names via _LEGACY_ENV_MAP
    """
    # Legacy env vars (lower priority — applied first)
    for env_name, (section_name, field_name) in _LEGACY_ENV_MAP.items():
        value = environ.get(env_name)
        if value is None:
            continue
        section = getattr(cfg, section_name, None)
        if section is None:
            continue
        if hasattr(section, field_name):
            current = getattr(section, field_name)
            setattr(section, field_name, _coerce(value, current))

    # Canonical CLEWSO_* env vars (higher priority — applied second)
    prefix = "CLEWSO_"
    for env_name, value in environ.items():
        if not env_name.startswith(prefix):
            continue
        rest = env_name[len(prefix) :].lower()
        # Match against section names
        for section_name in _SECTION_TYPES:
            section_prefix = section_name + "_"
            if rest.startswith(section_prefix):
                field_name = rest[len(section_prefix) :]
                section = getattr(cfg, section_name)
                if hasattr(section, field_name):
                    current = getattr(section, field_name)
                    setattr(section, field_name, _coerce(value, current))
                break


def load_config() -> ClewsoConfig:
    """Load configuration with full resolution chain."""
    cfg = ClewsoConfig()

    # 1. User config file (lowest priority)
    toml_data = _load_toml(CONFIG_FILE)
    _apply_dict(cfg, toml_data)

    # 2. Project .env file
    dotenv = _load_dotenv(Path.cwd() / ".env")

    # 3. Merge .env into real env (don't overwrite real env vars)
    merged_env = {**dotenv, **os.environ}

    # 4. Apply env vars (highest priority)
    _apply_env(cfg, merged_env)

    return cfg


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_config: ClewsoConfig | None = None


def get_config() -> ClewsoConfig:
    """Get the global config singleton. Loads on first access."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the singleton (for testing)."""
    global _config
    _config = None


# ---------------------------------------------------------------------------
# Config file management
# ---------------------------------------------------------------------------


def save_config(cfg: ClewsoConfig) -> Path:
    """Write config to ~/.config/clewso/config.toml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    lines = []
    for section_name in ("api", "embeddings", "store", "server", "review", "ci"):
        section = getattr(cfg, section_name)
        lines.append(f"[{section_name}]")
        for f in fields(section):
            value = getattr(section, f.name)
            if isinstance(value, bool):
                lines.append(f"{f.name} = {str(value).lower()}")
            elif isinstance(value, (int, float)):
                lines.append(f"{f.name} = {value}")
            else:
                lines.append(f'{f.name} = "{value}"')
        lines.append("")

    CONFIG_FILE.write_text("\n".join(lines))
    return CONFIG_FILE


def redact(value: str) -> str:
    """Redact a secret value for display."""
    if not value or len(value) < 8:
        return "***" if value else ""
    return value[:4] + "..." + value[-4:]
