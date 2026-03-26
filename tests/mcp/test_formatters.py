"""
Tests for response formatters.

Verifies that formatters correctly transform data into user-friendly output.
"""

from clew.mcp.formatters import (
    GraphFormatter,
    ModuleAnalysisFormatter,
    SearchResultFormatter,
    VerificationFormatter,
)


def test_graph_formatter_context():
    """Test parsing graph into incoming/outgoing relationships."""
    graph = {
        "nodes": [
            {"id": "node1", "name": "Module1"},
            {"id": "node2", "name": "Module2"},
            {"id": "node3", "name": "Module3"},
        ],
        "edges": [
            {"source": "node1", "target": "node2", "type": "IMPORTS"},
            {"source": "node3", "target": "node1", "type": "CALLS"},
        ],
    }

    incoming, outgoing = GraphFormatter.format_graph_context(graph, "node1")

    # node1 imports node2 (outgoing)
    assert len(outgoing) == 1
    assert outgoing[0]["target"] == "Module2"
    assert outgoing[0]["type"] == "IMPORTS"

    # node3 calls node1 (incoming)
    assert len(incoming) == 1
    assert incoming[0]["source"] == "Module3"
    assert incoming[0]["type"] == "CALLS"


def test_graph_formatter_mermaid():
    """Test Mermaid diagram generation."""
    graph = {
        "nodes": [
            {"id": "src/auth.py", "name": "auth"},
            {"id": "src/user.py", "name": "user"},
        ],
        "edges": [{"source": "src/auth.py", "target": "src/user.py", "type": "IMPORTS"}],
    }

    diagram = GraphFormatter.build_mermaid_diagram(graph, "src/auth.py")

    assert "```mermaid" in diagram
    assert "graph TD" in diagram
    assert "IMPORTS" in diagram
    assert ":::current" in diagram  # Focus node is highlighted


def test_search_result_formatter():
    """Test search result formatting."""
    results = [
        {"id": "1", "text": "code snippet", "score": 0.95, "metadata": {"path": "file.py"}},
        {"id": "2", "text": "another snippet", "score": 0.80, "metadata": {"path": "other.py"}},
    ]

    # Graph node IDs are paths (matching Neo4j output)
    graph = {
        "nodes": [{"id": "file.py", "name": "func"}],
        "edges": [{"source": "file.py", "target": "dep", "type": "IMPORTS"}],
    }

    context_data = [(results[0], graph)]

    output = SearchResultFormatter.format_search_results(results, context_data)

    assert "Found 2 matching items" in output
    assert "file.py" in output
    assert "0.95" in output
    assert "Relies On" in output  # Context section


def test_module_analysis_formatter():
    """Test module analysis formatting."""
    graph = {
        "nodes": [{"id": "mod", "name": "MyModule"}],
        "edges": [
            {"source": "mod", "target": "func1", "type": "DEFINES"},
            {"source": "mod", "target": "lib", "type": "IMPORTS"},
            {"source": "user", "target": "mod", "type": "CALLS"},
        ],
    }

    output = ModuleAnalysisFormatter.format_module_analysis("src/mod.py", graph, "mod")

    assert "Module Analysis: src/mod.py" in output
    assert "DEFINES:" in output
    assert "func1" in output
    assert "DEPENDENCIES (Imports):" in output
    assert "lib" in output
    assert "USAGE (Used By):" in output
    assert "user (CALLS)" in output
    assert "```mermaid" in output  # Diagram included


def test_verification_formatter_success():
    """Test verification formatting for found concepts."""
    results = [
        {"metadata": {"path": "auth.py"}, "score": 0.9},
        {"metadata": {"path": "login.py"}, "score": 0.8},
    ]

    output = VerificationFormatter.format_verification("authentication", results)

    assert "VERIFICATION SUCCESS" in output
    assert "found in 2 locations" in output
    assert "auth.py" in output
    assert "0.90" in output


def test_verification_formatter_failure():
    """Test verification formatting for missing concepts."""
    output = VerificationFormatter.format_verification("GraphQL", [])

    assert "VERIFICATION FAILED" in output
    assert "does NOT exist" in output
    assert "GraphQL" in output
