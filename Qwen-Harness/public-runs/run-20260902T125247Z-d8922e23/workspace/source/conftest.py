"""Put the first-party packages on sys.path for pytest.

``tests/`` carries no ``__init__.py``, so pytest inserts that directory rather
than the project root, which leaves ``routes``, ``environment`` and
``evaluation`` unimportable without this.
"""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
