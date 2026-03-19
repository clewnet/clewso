"""
Validate the sample fixture repo structure (no tree-sitter needed).

These tests ensure the fixture files exist, are syntactically valid Python,
and contain the patterns that tree-sitter is expected to extract. This runs
on any Python version and catches accidental fixture breakage.
"""

import ast
import re
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_repo"

EXPECTED_FILES = [
    "app.py",
    "config.py",
    "db.py",
    "models/__init__.py",
    "models/user.py",
    "routes/__init__.py",
    "routes/users.py",
    "utils/__init__.py",
    "utils/auth.py",
]


class TestFixtureStructure:
    """Verify the fixture repo is intact and parseable."""

    @pytest.mark.parametrize("rel_path", EXPECTED_FILES)
    def test_file_exists(self, rel_path):
        """Every expected fixture file exists on disk."""
        assert (FIXTURE_ROOT / rel_path).is_file(), f"Missing: {rel_path}"

    @pytest.mark.parametrize("rel_path", EXPECTED_FILES)
    def test_file_is_valid_python(self, rel_path):
        """Every fixture file parses without syntax errors."""
        source = (FIXTURE_ROOT / rel_path).read_text()
        try:
            ast.parse(source, filename=rel_path)
        except SyntaxError as e:
            pytest.fail(f"{rel_path} has a syntax error: {e}")


class TestFixtureContent:
    """Verify the fixture files contain the expected code patterns."""

    def _read(self, rel_path: str) -> str:
        return (FIXTURE_ROOT / rel_path).read_text()

    def test_app_imports_config_and_routes(self):
        src = self._read("app.py")
        assert "from config import" in src
        assert "from routes import" in src

    def test_app_defines_create_app(self):
        src = self._read("app.py")
        assert "def create_app" in src

    def test_config_defines_settings_class(self):
        src = self._read("config.py")
        assert "class Settings" in src

    def test_db_imports_config(self):
        src = self._read("db.py")
        assert "from config import" in src

    def test_db_defines_database_class(self):
        src = self._read("db.py")
        assert "class Database" in src
        assert "def save" in src

    def test_user_model_imports_db_and_auth(self):
        src = self._read("models/user.py")
        assert "from db import" in src
        assert "from utils.auth import" in src

    def test_user_model_defines_user_class(self):
        src = self._read("models/user.py")
        assert "class User" in src

    def test_routes_users_imports_across_modules(self):
        src = self._read("routes/users.py")
        assert "from config import" in src
        assert "from db import" in src
        assert "from models.user import" in src

    def test_auth_defines_hash_and_verify(self):
        src = self._read("utils/auth.py")
        assert "def hash_password" in src
        assert "def verify_password" in src

    def test_auth_imports_hashlib_and_secrets(self):
        src = self._read("utils/auth.py")
        assert "import hashlib" in src
        assert "import secrets" in src

    def test_cross_module_call_chain_exists(self):
        """The fixture has a call chain: routes/users.py → User → db.save → auth.hash_password."""
        users_src = self._read("routes/users.py")
        user_src = self._read("models/user.py")

        # routes/users.py calls User(...)
        assert "User(" in users_src
        # models/user.py calls hash_password(...)
        assert "hash_password(" in user_src
        # models/user.py calls db.save(...)
        assert "db.save(" in user_src

    def test_fixture_has_minimum_complexity(self):
        """The fixture has enough files and definitions to be non-trivial."""
        all_source = ""
        file_count = 0
        for rel in EXPECTED_FILES:
            p = FIXTURE_ROOT / rel
            if p.is_file():
                all_source += p.read_text() + "\n"
                file_count += 1

        # Count definitions (def + class)
        def_count = len(re.findall(r"^\s*(def |class )", all_source, re.MULTILINE))
        # Count imports
        import_count = len(re.findall(r"^\s*(import |from .+ import )", all_source, re.MULTILINE))

        assert file_count == 9, f"Expected 9 files, got {file_count}"
        assert def_count >= 10, f"Expected ≥10 defs, got {def_count}"
        assert import_count >= 12, f"Expected ≥12 imports, got {import_count}"
