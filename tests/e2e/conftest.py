"""E2E test configuration — adds clew-ingestion to sys.path."""

import sys
from pathlib import Path

# Add clew-ingestion/src/ so `clewso_ingestion.ingest` etc. resolve
ingestion_src = Path(__file__).parent.parent.parent / "packages" / "clew-ingestion" / "src"
sys.path.insert(0, str(ingestion_src))
