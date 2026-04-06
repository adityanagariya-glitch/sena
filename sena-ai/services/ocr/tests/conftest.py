"""OCR service test configuration."""

from __future__ import annotations

import sys
from pathlib import Path

# Add service src and shared src to path for test imports
service_src = Path(__file__).parent.parent / "src"
shared_src = Path(__file__).parent.parent.parent.parent / "shared" / "src"
sys.path.insert(0, str(service_src))
sys.path.insert(0, str(shared_src))
