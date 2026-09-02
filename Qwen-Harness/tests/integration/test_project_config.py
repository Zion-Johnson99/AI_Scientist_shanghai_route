from __future__ import annotations

from pathlib import Path

from qwen_harness.config import validate_all_configs

HARNESS_ROOT = Path(__file__).resolve().parents[2]


def test_repository_configuration_files_are_valid() -> None:
    assert validate_all_configs(HARNESS_ROOT) == []
