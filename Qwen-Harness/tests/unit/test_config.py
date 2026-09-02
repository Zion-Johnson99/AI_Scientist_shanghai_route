from __future__ import annotations

from pathlib import Path

import pytest

from qwen_harness.config import env_diagnostics, load_settings
from qwen_harness.errors import ConfigError

ENV_NAMES = (
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "QWEN_HARNESS_MODEL",
    "QWEN_HARNESS_TIMEOUT_SECONDS",
    "QWEN_HARNESS_NETWORK_ENABLED",
    "QWEN_HARNESS_MAX_ITERATIONS",
    "QWEN_HARNESS_DEFAULT_REASONING_EFFORT",
    "QWEN_HARNESS_RUNTIME_ROOT",
)


def _clear_harness_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_load_settings_reads_local_env_without_exposing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_harness_environment(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "DASHSCOPE_API_KEY=test-only-key",
                "DASHSCOPE_BASE_URL=https://workspace.example.invalid/compatible-mode/v1",
                "QWEN_HARNESS_NETWORK_ENABLED=true",
                "QWEN_HARNESS_MAX_ITERATIONS=3",
            )
        ),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)
    diagnostics = env_diagnostics(settings)

    assert settings.env_file_exists is True
    assert settings.api_key_configured is True
    assert settings.network_enabled is True
    assert settings.max_iterations == 3
    assert all("test-only-key" not in str(problem) for problem in diagnostics)


def test_load_settings_rejects_non_integer_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_harness_environment(monkeypatch)
    monkeypatch.setenv("QWEN_HARNESS_TIMEOUT_SECONDS", "slow")

    with pytest.raises(ConfigError, match="不是整数"):
        load_settings(tmp_path)


def test_env_diagnostics_marks_placeholder_base_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_harness_environment(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://<WorkspaceId>.example.invalid/v1")

    problems = env_diagnostics(load_settings(tmp_path))

    assert any(
        problem["item"] == "DASHSCOPE_BASE_URL" and problem["level"] == "error"
        for problem in problems
    )
