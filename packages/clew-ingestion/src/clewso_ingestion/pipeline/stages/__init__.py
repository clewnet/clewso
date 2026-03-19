"""
Pipeline stages implementing the Chain of Responsibility pattern.

Each stage handles one specific concern:
1. RepositoryPreparationStage: Clone or validate repository
2. FileDiscoveryStage: Find and filter files to process
3. ParsingStage: Parse files and extract AST nodes
4. ProcessingStage: Process nodes using registered processors
5. FinalizationStage: Flush databases and cleanup
"""

from .discovery import FileDiscoveryStage
from .finalization import FinalizationStage
from .parsing import ParsingStage
from .processing import ProcessingStage
from .repository import RepositoryPreparationStage
from .signature_extraction import SignatureExtractionStage

__all__ = [
    "RepositoryPreparationStage",
    "FileDiscoveryStage",
    "ParsingStage",
    "ProcessingStage",
    "SignatureExtractionStage",
    "FinalizationStage",
]
