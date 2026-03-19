import sys
from unittest.mock import MagicMock

import pytest

sys.modules["tree_sitter"] = MagicMock()
sys.modules["tree_sitter_language_pack"] = MagicMock()
from clewso_ingestion.parser import (  # noqa: E402
    CodeParser,
    _get_import_go,
    _get_import_js,
    _get_import_python,
)

# Test data for different languages
PYTHON_CODE = """
import os
import sys as system
from datetime import datetime
from . import utils
from .models import User
"""

JS_CODE = """
import React from 'react';
import { useState, useEffect } from 'react';
import Button from './components/Button';
const fs = require('fs'); // Should not be picked up by import logic yet (focused on import statements)
"""

GO_CODE = """
package main

import (
	"fmt"
	"net/http"
    json "encoding/json"
)

import "os"
"""


@pytest.fixture
def parser():
    return CodeParser()


def test_extract_python_imports(parser):
    # Mocking or using actual parser if languages are available.
    # Since we can't easily mock the tree-sitter library in this environment without complex mocking,
    # we will rely on the actual parser method logic if we can instantiate it.

    # However, to test effectively without depending on the tree-sitter binaries being present/loadable
    # in this environment:
    # We can mock the node structure.
    # But CodeParser relies on tree-sitter.

    # Integration test approach:
    # If we assume tree-sitter is installed and languages are available (which they should be in the real env),
    # we can run it.

    # For now, let's try to parse. failed parsing returns empty.
    # We will need to check if we can load languages.

    # If languages fail to load (e.g. missing .so files), these tests will fail or skip.
    # Let's assume the environment is set up correctly as per previous logs.

    # Actually, previous logs showed "Simulated failure" for loading languages in some contexts.
    # Let's write the test to be robust or mock the internal _term/node if needed.

    # But wait, we implemented _get_import_name_python which takes a Node.
    # We can mock the Node object to test the logic in isolation from Tree-sitter!

    from unittest.mock import MagicMock

    # Helper to create a mock node
    def create_mock_node(type, children=None, text=None, fields=None):
        node = MagicMock()
        node.type = type
        node.children = children or []
        node.text = text.encode("utf-8") if text else None

        def child_by_field_name(name):
            return fields.get(name) if fields else None

        node.child_by_field_name = child_by_field_name
        return node

    # Test Python 'import os'
    # Structure: import_statement -> dotted_name(os)
    node_import_os = create_mock_node("import_statement", children=[create_mock_node("dotted_name", text="os")])
    assert _get_import_python(node_import_os) == "os"

    # Test Python 'import sys as system'
    # Structure: import_statement -> aliased_import -> (name: dotted_name(sys), alias: identifier(system))
    node_aliased_Sys = create_mock_node("aliased_import", fields={"name": create_mock_node("dotted_name", text="sys")})
    node_import_nav = create_mock_node("import_statement", children=[node_aliased_Sys])
    assert _get_import_python(node_import_nav) == "sys"

    # Test Python 'from datetime import datetime'
    # Structure: import_from_statement -> module_name(datetime) ...
    node_from_import = create_mock_node(
        "import_from_statement", fields={"module_name": create_mock_node("dotted_name", text="datetime")}
    )
    assert _get_import_python(node_from_import) == "datetime"

    # Test Python 'from . import utils'
    # Structure: import_from_statement -> relative_import(.) -> ...
    # This might vary by grammar version, but usually module_name is None, and there is a relative_import child.
    node_relative = create_mock_node("import_from_statement", children=[create_mock_node("relative_import", text=".")])
    # The current logic checks for module_name first, then relative_import child
    assert _get_import_python(node_relative) == "."


def test_extract_javascript_imports(parser):
    from unittest.mock import MagicMock

    def create_mock_node(type, text=None, fields=None):
        node = MagicMock()
        node.type = type
        node.text = text.encode("utf-8") if text else None
        node.child_by_field_name = lambda name: fields.get(name) if fields else None
        return node

    # Test 'import React from "react"'
    # Structure: import_statement -> source: string("react")
    node_import = create_mock_node("import_statement", fields={"source": create_mock_node("string", text="'react'")})

    assert _get_import_js(node_import) == "react"


def test_extract_go_imports(parser):
    from unittest.mock import MagicMock

    def create_mock_node(type, text=None, fields=None, children=None):
        node = MagicMock()
        node.type = type
        node.children = children or []
        node.text = text.encode("utf-8") if text else None
        node.child_by_field_name = lambda name: fields.get(name) if fields else None
        return node

    # Test 'import "fmt"'
    # Structure: import_spec -> path: string("fmt")
    node_import = create_mock_node("import_spec", fields={"path": create_mock_node("string", text='"fmt"')})
    assert _get_import_go(node_import) == "fmt"

    # Test block import child
    # Structure: import_declaration -> import_spec ...
    # The traversal logic in parser handles strictly 'import_types'.
    # If we register 'import_spec', then _traverse calls _get_import_name with the spec node.
    # So we only need to test import_spec handling here.

    node_import_json = create_mock_node(
        "import_spec", fields={"path": create_mock_node("string", text='"encoding/json"')}
    )
    assert _get_import_go(node_import_json) == "encoding/json"
