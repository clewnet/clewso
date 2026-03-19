"""
Configuration for pytest.
"""

import pytest


@pytest.fixture
def sample_diff():
    """Sample git diff for testing."""
    return """diff --git a/src/example.py b/src/example.py
index 1234567..abcdefg 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,5 @@
 def example():
+    # New implementation
+    return True
     pass
"""
