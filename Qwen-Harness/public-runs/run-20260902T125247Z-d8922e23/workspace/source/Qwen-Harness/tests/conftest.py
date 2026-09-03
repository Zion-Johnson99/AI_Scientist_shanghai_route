"""Put both the harness copy and the generated workspace root on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COPY_ROOT = HERE.parent
SOURCE_ROOT = COPY_ROOT.parent
for candidate in (str(SOURCE_ROOT), str(COPY_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
