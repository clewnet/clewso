"""
End-to-end test: ingest the sample fixture repo and verify the full pipeline.

This test uses a REAL CodeParser (tree-sitter) against the fixture files in
tests/fixtures/sample_repo/, but mocks the database backends (Qdrant, Neo4j)
so it can run without Docker. It exercises the complete pipeline:

    RepositoryPreparation → FileDiscovery → Parsing → Processing → Finalization

What it proves:
    1. Tree-sitter correctly parses the fixture files (definitions, imports, calls)
    2. The pipeline wires parsed AST nodes into the correct graph store calls
    3. All expected graph relationships are created (CONTAINS, DEFINES, IMPORTS, CALLS)
    4. Vector store receives file-level and definition-level embeddings
    5. The fixture repo is a valid, non-trivial test case

This is NOT a unit test — it integrates multiple real components and only mocks
the I/O boundaries (databases).
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# tree-sitter-language-pack requires Python >=3.10; skip gracefully if unavailable.
try:
    HAS_TREE_SITTER = importlib.util.find_spec("tree_sitter_language_pack") is not None
except (ImportError, AttributeError):
    HAS_TREE_SITTER = False

pytestmark = pytest.mark.skipif(
    not HAS_TREE_SITTER,
    reason="tree-sitter-language-pack not installed",
)

# ---------------------------------------------------------------------------
# Fixture path (relative to repo root)
# ---------------------------------------------------------------------------
FIXTURE_REPO = str(Path(__file__).parent.parent / "fixtures" / "sample_repo")

# ---------------------------------------------------------------------------
# Expected graph structure — the contract the fixture repo satisfies.
# These are the file-relative paths that FileDiscovery should find.
# ---------------------------------------------------------------------------
EXPECTED_FILES = {
    "app.py",
    "config.py",
    "db.py",
    "models/__init__.py",
    "models/user.py",
    "routes/__init__.py",
    "routes/users.py",
    "utils/__init__.py",
    "utils/auth.py",
}

# Definitions tree-sitter should extract (file_path, name, kind).
# Only includes definitions, not imports/calls.
EXPECTED_DEFINITIONS = {
    # app.py
    ("app.py", "create_app", "function_definition"),
    ("app.py", "main", "function_definition"),
    # config.py
    ("config.py", "Settings", "class_definition"),
    ("config.py", "get_settings", "function_definition"),
    # db.py
    ("db.py", "Database", "class_definition"),
    ("db.py", "get_db", "function_definition"),
    # models/user.py
    ("models/user.py", "User", "class_definition"),
    # routes/__init__.py
    ("routes/__init__.py", "register_routes", "function_definition"),
    # routes/users.py
    ("routes/users.py", "handle_create_user", "function_definition"),
    ("routes/users.py", "handle_get_user", "function_definition"),
    # utils/auth.py
    ("utils/auth.py", "hash_password", "function_definition"),
    ("utils/auth.py", "verify_password", "function_definition"),
}

# Imports the parser should extract (file_path, module_name).
# Based on _get_import_name_python logic:
#   - `import X`        → "X"
#   - `from X import Y` → "X"
EXPECTED_IMPORTS = {
    # app.py: from config import Settings; from routes import register_routes
    ("app.py", "config"),
    ("app.py", "routes"),
    # db.py: from config import Settings (sqlite3 is stdlib, filtered)
    ("db.py", "config"),
    # models/__init__.py: from models.user import User
    ("models/__init__.py", "models.user"),
    # models/user.py: from db import Database; from utils.auth import ...
    ("models/user.py", "db"),
    ("models/user.py", "utils.auth"),
    # routes/__init__.py: from routes.users import ...
    ("routes/__init__.py", "routes.users"),
    # routes/users.py: from config import ...; from db import ...; from models.user import ...
    ("routes/users.py", "config"),
    ("routes/users.py", "db"),
    ("routes/users.py", "models.user"),
    # Note: stdlib imports (os, sqlite3, hashlib, secrets) are filtered during ingestion
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_mock_vs(mock_vs):
    """Configure a mock VectorStore for the async pipeline.

    Sets up both sync ``add()`` (used by ProcessingStage for definitions) and
    async ``add_batch()`` (used by ParsingStage for file-level embeddings).
    """
    mock_vs.add.return_value = "mock_id"
    mock_vs.add_batch = AsyncMock(side_effect=lambda items: [f"mock_batch_id_{i}" for i in range(len(items))])
    mock_vs.flush = AsyncMock()
    return mock_vs


def _extract_files(mock_graph) -> set[str]:
    """Extract created files from mock calls."""
    files_created = set()
    for call in mock_graph.create_file_node.call_args_list:
        files_created.add(call.kwargs.get("file_path") or call.args[1])

    for call in mock_graph.create_file_nodes_batch.call_args_list:
        items = call.kwargs.get("items") or call.args[1]
        for item in items:
            files_created.add(item["file_path"])
    return files_created


def _extract_definitions(mock_graph) -> set[tuple[str, str, str]]:
    """Extract created definitions (file_path, name, type) from mock calls."""
    definitions_created = set()
    for call in mock_graph.create_code_node.call_args_list:
        kw = call.kwargs
        definitions_created.add(
            (
                kw.get("file_path", call.args[1] if len(call.args) > 1 else None),
                kw.get("name", call.args[2] if len(call.args) > 2 else None),
                kw.get("node_type", call.args[3] if len(call.args) > 3 else None),
            )
        )
    return definitions_created


def _extract_relationships(mock_graph) -> tuple[set, set]:
    """Extract imports and calls from mock calls."""
    imports_created = set()
    calls_created = set()

    for call in mock_graph.create_import_relationship.call_args_list:
        kw = call.kwargs
        imports_created.add(
            (
                kw.get("file_path", call.args[1] if len(call.args) > 1 else None),
                kw.get("module_name", call.args[2] if len(call.args) > 2 else None),
            )
        )

    for call in mock_graph.create_call_relationship.call_args_list:
        kw = call.kwargs
        calls_created.add(
            (
                kw.get("file_path", call.args[1] if len(call.args) > 1 else None),
                kw.get("target_name", call.args[2] if len(call.args) > 2 else None),
            )
        )
    return imports_created, calls_created


def _extract_graph_calls(mock_graph):
    """Extract structured data from graph store mock calls."""
    files_created = _extract_files(mock_graph)
    definitions_created = _extract_definitions(mock_graph)
    imports_created, calls_created = _extract_relationships(mock_graph)

    # Also parse execute_batch calls (used by batched processing path)
    _parse_batched_operations(mock_graph, definitions_created, imports_created, calls_created)

    return files_created, definitions_created, imports_created, calls_created


def _parse_batched_operations(mock_graph, definitions_created, imports_created, calls_created):
    """Parse execute_batch calls and populate creation sets."""
    for call in mock_graph.execute_batch.call_args_list:
        operations = call[0][0]  # First positional arg is the list of operations
        for cypher, params in operations:
            if "CodeBlock" in cypher:
                # This is a code node (definition)
                definitions_created.add(
                    (
                        params.get("file_path"),
                        params.get("name"),
                        params.get("node_type"),
                    )
                )
            elif "Module" in cypher and "IMPORTS" in cypher:
                # This is an import
                imports_created.add(
                    (
                        params.get("file_path"),
                        params.get("module_name"),
                    )
                )
            elif "Function" in cypher and "CALLS" in cypher:
                # This is a call
                calls_created.add(
                    (
                        params.get("file_path"),
                        params.get("target_name"),
                    )
                )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_external_deps():
    """Mock only the C-extension / network dependencies, NOT CodeParser."""
    mock_modules = {
        "git": MagicMock(),
        "qdrant_client": MagicMock(),
        "qdrant_client.http": MagicMock(),
        "qdrant_client.http.models": MagicMock(),
        "neo4j": MagicMock(),
    }

    # Clean up to avoid stale imports
    to_reload = ["clewso_ingestion.ingest", "clewso_ingestion.vector", "clewso_ingestion.graph"]
    for mod in to_reload:
        if mod in sys.modules:
            del sys.modules[mod]

    with patch.dict(sys.modules, mock_modules):
        yield

    for mod in to_reload:
        if mod in sys.modules:
            del sys.modules[mod]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFixtureRepoIngestion:
    """Ingest the sample fixture repo and verify the full graph structure."""

    def test_pipeline_succeeds(self, mock_external_deps):
        """Pipeline completes successfully on the fixture repo."""
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore"),
        ):
            _setup_mock_vs(mock_vs_cls.return_value)

            exit_code = ingest_repo("fixture-repo", FIXTURE_REPO)

        assert exit_code == 0

    def test_all_files_discovered(self, mock_external_deps):
        """FileDiscovery finds all 9 Python files in the fixture."""
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore") as mock_gs_cls,
        ):
            _setup_mock_vs(mock_vs_cls.return_value)
            mock_gs = mock_gs_cls.return_value

            ingest_repo("fixture-repo", FIXTURE_REPO)

            files_created, _, _, _ = _extract_graph_calls(mock_gs)
            assert files_created == EXPECTED_FILES

    def test_definitions_extracted(self, mock_external_deps):
        """Tree-sitter extracts all expected function/class definitions."""
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore") as mock_gs_cls,
        ):
            _setup_mock_vs(mock_vs_cls.return_value)
            mock_gs = mock_gs_cls.return_value

            ingest_repo("fixture-repo", FIXTURE_REPO)

            _, definitions, _, _ = _extract_graph_calls(mock_gs)

            # Check that all expected definitions were found
            missing = EXPECTED_DEFINITIONS - definitions
            assert not missing, f"Missing definitions: {missing}"

    def test_imports_extracted(self, mock_external_deps):
        """Tree-sitter extracts all expected import relationships."""
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore") as mock_gs_cls,
        ):
            _setup_mock_vs(mock_vs_cls.return_value)
            mock_gs = mock_gs_cls.return_value

            ingest_repo("fixture-repo", FIXTURE_REPO)

            _, _, imports, _ = _extract_graph_calls(mock_gs)

            missing = EXPECTED_IMPORTS - imports
            assert not missing, f"Missing imports: {missing}"

    def test_calls_extracted(self, mock_external_deps):
        """Tree-sitter extracts cross-module function calls."""
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore") as mock_gs_cls,
        ):
            _setup_mock_vs(mock_vs_cls.return_value)
            mock_gs = mock_gs_cls.return_value

            ingest_repo("fixture-repo", FIXTURE_REPO)

            _, _, _, calls = _extract_graph_calls(mock_gs)

            # Verify key cross-module calls exist
            # routes/users.py should call: get_settings(), get_db(), User(), ...
            call_files = {f for f, _ in calls}
            assert "routes/users.py" in call_files, "routes/users.py should have calls"
            assert "models/user.py" in call_files, "models/user.py should have calls"
            assert "app.py" in call_files, "app.py should have calls"

            # Verify specific high-value calls
            call_targets = {t for _, t in calls}
            assert "hash_password" in call_targets, "hash_password should be a call target"

    def test_vector_store_receives_embeddings(self, mock_external_deps):
        """VectorStore receives file-level and definition-level content."""
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore"),
        ):
            mock_vs = _setup_mock_vs(mock_vs_cls.return_value)

            ingest_repo("fixture-repo", FIXTURE_REPO)

            # Definition-level embeddings now verify via add_batch too
            # assert mock_vs.add.call_count >= len(EXPECTED_DEFINITIONS)  <-- removed

            # File-level AND definition-level embeddings go through add_batch()
            assert mock_vs.add_batch.call_count >= 1
            batch_items = []
            for call in mock_vs.add_batch.call_args_list:
                batch_items.extend(call.args[0])

            file_type_items = []
            definition_items = []

            for item in batch_items:
                # Handle 2-tuple or 3-tuple
                if len(item) == 3:
                    text, meta, _ = item
                else:
                    text, meta = item

                if meta.get("type") == "file":
                    file_type_items.append((text, meta))
                elif meta.get("type") in ("function_definition", "class_definition"):
                    definition_items.append((text, meta))

            assert len(file_type_items) == len(EXPECTED_FILES)
            assert len(definition_items) >= len(EXPECTED_DEFINITIONS)

    def test_repo_node_created(self, mock_external_deps):
        """A Repository node is created in the graph store."""
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore") as mock_gs_cls,
        ):
            _setup_mock_vs(mock_vs_cls.return_value)

            mock_gs = mock_gs_cls.return_value

            ingest_repo("fixture-repo", FIXTURE_REPO)

            mock_gs.create_repo_node.assert_called_once_with("fixture-repo", "sample_repo", FIXTURE_REPO)

    def test_graph_has_expected_shape(self, mock_external_deps):
        """
        Aggregate shape check: the fixture produces a non-trivial graph
        with the right order of magnitude.
        """
        from clewso_ingestion.ingest import ingest_repo

        with (
            patch("clewso_ingestion.ingest.VectorStore") as mock_vs_cls,
            patch("clewso_ingestion.ingest.GraphStore") as mock_gs_cls,
        ):
            _setup_mock_vs(mock_vs_cls.return_value)
            mock_gs = mock_gs_cls.return_value

            ingest_repo("fixture-repo", FIXTURE_REPO)

            files, defs, imports, calls = _extract_graph_calls(mock_gs)

            # Shape assertions — the fixture should produce:
            assert len(files) == 9, f"Expected 9 files, got {len(files)}"
            assert len(defs) >= 10, f"Expected ≥10 definitions, got {len(defs)}"
            assert len(imports) >= 8, f"Expected ≥8 imports, got {len(imports)}"
            assert len(calls) >= 5, f"Expected ≥5 calls, got {len(calls)}"
