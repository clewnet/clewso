"""
Node processors implementing the Strategy pattern.

Each processor handles a specific type of AST node:
- DefinitionProcessor: Functions, classes, methods
- ImportProcessor: Import statements
- CallProcessor: Function calls
"""

from .call import CallProcessor
from .definition import DefinitionProcessor
from .import_processor import ImportProcessor
from .registry import NodeProcessorRegistry

__all__ = [
    "DefinitionProcessor",
    "ImportProcessor",
    "CallProcessor",
    "NodeProcessorRegistry",
]
