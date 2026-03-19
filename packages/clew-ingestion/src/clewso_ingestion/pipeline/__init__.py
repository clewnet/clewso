"""
Ingestion Pipeline Module

This module provides a refactored, object-oriented ingestion pipeline
that follows SOLID principles and Gang of Four design patterns.

The pipeline architecture uses:
- Pipeline Pattern: Composable stages for processing
- Strategy Pattern: Pluggable node processors
- Chain of Responsibility: Sequential stage processing
"""

from .context import FileItem, IngestionContext, ProcessingResult
from .orchestrator import IngestionPipeline

__all__ = ["IngestionPipeline", "IngestionContext", "FileItem", "ProcessingResult"]
