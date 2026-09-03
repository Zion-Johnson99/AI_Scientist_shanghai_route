"""Environment data project root for the 54-cell Xuhui exposure grid."""

from __future__ import annotations

from pathlib import Path

MODULE_ROOT: Path = Path(__file__).resolve().parent
GRID_ROWS: int = 6
GRID_COLS: int = 9
GRID_CELL_COUNT: int = GRID_ROWS * GRID_COLS
CANONICAL_CRS: str = "CRS84/WGS84 (lon,lat)"

__all__ = ["CANONICAL_CRS", "GRID_CELL_COUNT", "GRID_COLS", "GRID_ROWS", "MODULE_ROOT"]
