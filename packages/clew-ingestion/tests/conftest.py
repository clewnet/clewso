"""
Pytest configuration for clew-ingestion tests.
Adds src/ to sys.path so tests can import from clewso_ingestion.
"""

import sys
from pathlib import Path

# Add src/ so that `import clewso_ingestion` resolves to src/clewso_ingestion/
src_root = Path(__file__).parent.parent / "src"
if str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))
