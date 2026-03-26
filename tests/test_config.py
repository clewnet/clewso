"""Tests for the unified config module."""

import textwrap

import pytest

from clew.config import (
    ClewsoConfig,
    _apply_dict,
    _apply_env,
    _load_dotenv,
    get_config,
    load_config,
    redact,
    reset_config,
    save_config,
)


@pytest.fixture(autouse=True)
def _clean_config():
    """Reset config singleton between tests."""
    reset_config()
    yield
    reset_config()


class TestDefaults:
    def test_default_api_url(self):
        cfg = ClewsoConfig()
        assert cfg.api.url == "http://localhost:8000/v1"

    def test_default_embeddings_provider(self):
        cfg = ClewsoConfig()
        assert cfg.embeddings.provider == "openai"

    def test_default_store_ports(self):
        cfg = ClewsoConfig()
        assert cfg.store.qdrant_port == 6335
        assert cfg.store.neo4j_uri == "bolt://localhost:7687"

    def test_default_server_config(self):
        cfg = ClewsoConfig()
        assert cfg.server.rerank_enabled is False
        assert cfg.server.graph_boost_weight == 0.05

    def test_default_ci_mode(self):
        cfg = ClewsoConfig()
        assert cfg.ci.write_mode == "open"


class TestTomlLoading:
    def test_apply_dict_updates_fields(self):
        cfg = ClewsoConfig()
        _apply_dict(
            cfg,
            {
                "api": {"url": "https://api.example.com", "key": "test-key"},
                "store": {"qdrant_port": 9999},
            },
        )
        assert cfg.api.url == "https://api.example.com"
        assert cfg.api.key == "test-key"
        assert cfg.store.qdrant_port == 9999

    def test_apply_dict_ignores_unknown_sections(self):
        cfg = ClewsoConfig()
        _apply_dict(cfg, {"nonexistent": {"foo": "bar"}})
        # Should not raise

    def test_apply_dict_ignores_unknown_fields(self):
        cfg = ClewsoConfig()
        _apply_dict(cfg, {"api": {"nonexistent_field": "value"}})
        # Should not raise

    def test_load_from_toml_file(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            textwrap.dedent("""\
            [api]
            url = "https://prod.clewso.sh"
            key = "sk-prod-123"

            [store]
            neo4j_uri = "bolt://db.internal:7687"
        """)
        )

        from clew.config import _load_toml

        data = _load_toml(toml_file)
        assert data["api"]["url"] == "https://prod.clewso.sh"
        assert data["store"]["neo4j_uri"] == "bolt://db.internal:7687"


class TestEnvVars:
    def test_canonical_clewso_prefix(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CLEWSO_API_URL": "http://custom:9000"})
        assert cfg.api.url == "http://custom:9000"

    def test_canonical_nested_field(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CLEWSO_STORE_QDRANT_PORT": "7777"})
        assert cfg.store.qdrant_port == 7777

    def test_canonical_bool_coercion(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CLEWSO_SERVER_RERANK_ENABLED": "true"})
        assert cfg.server.rerank_enabled is True

    def test_canonical_float_coercion(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CLEWSO_SERVER_GRAPH_BOOST_WEIGHT": "0.15"})
        assert cfg.server.graph_boost_weight == 0.15

    def test_legacy_openai_api_key(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"OPENAI_API_KEY": "sk-test-abc"})
        assert cfg.embeddings.openai_api_key == "sk-test-abc"

    def test_legacy_clew_api_url(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CLEW_API_URL": "http://old-style:8000/v1"})
        assert cfg.api.url == "http://old-style:8000/v1"

    def test_legacy_neo4j(self):
        cfg = ClewsoConfig()
        _apply_env(
            cfg,
            {
                "NEO4J_URI": "bolt://custom:7687",
                "NEO4J_USER": "admin",
                "NEO4J_PASSWORD": "secret",
            },
        )
        assert cfg.store.neo4j_uri == "bolt://custom:7687"
        assert cfg.store.neo4j_user == "admin"
        assert cfg.store.neo4j_password == "secret"

    def test_legacy_context_engine_api_url(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CONTEXT_ENGINE_API_URL": "http://mcp-compat:8000"})
        assert cfg.api.url == "http://mcp-compat:8000"

    def test_canonical_overrides_legacy(self):
        cfg = ClewsoConfig()
        _apply_env(
            cfg,
            {
                "CLEW_API_URL": "http://legacy",
                "CLEWSO_API_URL": "http://canonical",
            },
        )
        assert cfg.api.url == "http://canonical"

    def test_legacy_write_mode(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CLEW_WRITE_MODE": "ci-only", "CLEW_CI_TOKEN": "tok-123"})
        assert cfg.ci.write_mode == "ci-only"
        assert cfg.ci.ci_token == "tok-123"

    def test_legacy_qdrant_cloud_env(self):
        cfg = ClewsoConfig()
        _apply_env(
            cfg,
            {
                "QDRANT_API_ENDPOINT": "https://xyz.aws.cloud.qdrant.io:6333",
                "QDRANT_API_TOKEN": "tok-qdrant-123",
            },
        )
        assert cfg.store.qdrant_url == "https://xyz.aws.cloud.qdrant.io:6333"
        assert cfg.store.qdrant_api_key == "tok-qdrant-123"

    def test_qdrant_url_alias(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"QDRANT_URL": "https://alt.qdrant.io"})
        assert cfg.store.qdrant_url == "https://alt.qdrant.io"

    def test_qdrant_api_key_alias(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"QDRANT_API_KEY": "key-alt"})
        assert cfg.store.qdrant_api_key == "key-alt"

    def test_canonical_qdrant_url(self):
        cfg = ClewsoConfig()
        _apply_env(cfg, {"CLEWSO_STORE_QDRANT_URL": "https://canonical.qdrant.io"})
        assert cfg.store.qdrant_url == "https://canonical.qdrant.io"

    def test_legacy_server_adapters(self):
        cfg = ClewsoConfig()
        _apply_env(
            cfg,
            {
                "CLEW_VECTOR_ADAPTER": "pgvector",
                "CLEW_GRAPH_ADAPTER": "noop",
            },
        )
        assert cfg.server.vector_adapter == "pgvector"
        assert cfg.server.graph_adapter == "noop"


class TestDotenv:
    def test_parse_simple(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        result = _load_dotenv(env_file)
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_parse_quoted_values(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=\"quoted value\"\nKEY2='single'\n")
        result = _load_dotenv(env_file)
        assert result["KEY"] == "quoted value"
        assert result["KEY2"] == "single"

    def test_skip_comments_and_blanks(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY=val\n")
        result = _load_dotenv(env_file)
        assert result == {"KEY": "val"}

    def test_missing_file_returns_empty(self, tmp_path):
        result = _load_dotenv(tmp_path / "nonexistent")
        assert result == {}


class TestResolutionChain:
    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        # Write a TOML config
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[api]\nurl = "http://from-toml"\n')

        # Patch CONFIG_FILE to use our temp file
        monkeypatch.setattr("clew.config.CONFIG_FILE", toml_file)
        monkeypatch.setenv("CLEWSO_API_URL", "http://from-env")
        monkeypatch.chdir(tmp_path)

        cfg = load_config()
        assert cfg.api.url == "http://from-env"

    def test_toml_applies_without_env(self, tmp_path, monkeypatch):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[api]\nurl = "http://from-toml"\n')

        monkeypatch.setattr("clew.config.CONFIG_FILE", toml_file)
        monkeypatch.delenv("CLEWSO_API_URL", raising=False)
        monkeypatch.delenv("CLEW_API_URL", raising=False)
        monkeypatch.chdir(tmp_path)

        cfg = load_config()
        assert cfg.api.url == "http://from-toml"

    def test_dotenv_applies(self, tmp_path, monkeypatch):
        dotenv = tmp_path / ".env"
        dotenv.write_text("OPENAI_API_KEY=sk-from-dotenv\n")

        monkeypatch.setattr("clew.config.CONFIG_FILE", tmp_path / "nonexistent.toml")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CLEWSO_EMBEDDINGS_OPENAI_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)

        cfg = load_config()
        assert cfg.embeddings.openai_api_key == "sk-from-dotenv"

    def test_real_env_overrides_dotenv(self, tmp_path, monkeypatch):
        dotenv = tmp_path / ".env"
        dotenv.write_text("OPENAI_API_KEY=sk-from-dotenv\n")

        monkeypatch.setattr("clew.config.CONFIG_FILE", tmp_path / "nonexistent.toml")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-real-env")
        monkeypatch.chdir(tmp_path)

        cfg = load_config()
        assert cfg.embeddings.openai_api_key == "sk-from-real-env"


class TestSingleton:
    def test_get_config_returns_same_instance(self, tmp_path, monkeypatch):
        monkeypatch.setattr("clew.config.CONFIG_FILE", tmp_path / "nonexistent.toml")
        monkeypatch.chdir(tmp_path)

        a = get_config()
        b = get_config()
        assert a is b

    def test_reset_forces_reload(self, tmp_path, monkeypatch):
        monkeypatch.setattr("clew.config.CONFIG_FILE", tmp_path / "nonexistent.toml")
        monkeypatch.chdir(tmp_path)

        a = get_config()
        reset_config()
        b = get_config()
        assert a is not b


class TestSaveConfig:
    def test_roundtrip(self, tmp_path):
        cfg = ClewsoConfig()
        cfg.api.url = "https://saved.example.com"
        cfg.api.key = "sk-roundtrip"
        cfg.store.qdrant_port = 1234
        cfg.server.rerank_enabled = True

        import clew.config as config_mod
        from clew.config import _load_toml

        # Save to temp dir
        original_dir = config_mod.CONFIG_DIR
        original_file = config_mod.CONFIG_FILE
        config_mod.CONFIG_DIR = tmp_path
        config_mod.CONFIG_FILE = tmp_path / "config.toml"
        try:
            save_config(cfg)
            data = _load_toml(config_mod.CONFIG_FILE)
        finally:
            config_mod.CONFIG_DIR = original_dir
            config_mod.CONFIG_FILE = original_file

        assert data["api"]["url"] == "https://saved.example.com"
        assert data["api"]["key"] == "sk-roundtrip"
        assert data["store"]["qdrant_port"] == 1234
        assert data["server"]["rerank_enabled"] is True


class TestRedact:
    def test_redact_long_string(self):
        assert redact("sk-1234567890abcdef") == "sk-1...cdef"

    def test_redact_short_string(self):
        assert redact("short") == "***"

    def test_redact_empty(self):
        assert redact("") == ""
