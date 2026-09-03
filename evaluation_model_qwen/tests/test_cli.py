from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from evaluation_model_qwen.cli import format_environment, interactive_profile, main
from evaluation_model_qwen.models import ApiAudit
from evaluation_model_qwen.qwen_client import QwenClient


class DegradedClient:
    def api_check(self) -> ApiAudit:
        return ApiAudit(
            status="degraded",
            model="qwen3.8-flash",
            error_type="authentication",
            error_message="千问身份验证失败",
        )


def fake_from_env(
    cls: type[QwenClient],
    env_file: Path | None = None,
    *,
    client: object | None = None,
) -> DegradedClient:
    del cls, env_file, client
    return DegradedClient()


def test_api_check_returns_failure_exit_code_for_degraded_audit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        QwenClient,
        "from_env",
        classmethod(fake_from_env),
    )

    exit_code = main(["api-check", "--json", "--env-file", str(tmp_path / ".env")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"status": "degraded"' in captured.out
    assert "authentication" in captured.out


def test_interactive_questionnaire_reads_configured_fourth_run_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(["2", "4", "", "", "", "", "", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    profile = interactive_profile()

    assert profile.route_mode == "run"
    assert (
        profile.distance_min_m,
        profile.target_distance_m,
        profile.distance_max_m,
    ) == (10000, 12000, 14000)


def test_human_environment_summary_is_encodable_by_windows_console() -> None:
    text = format_environment(
        {
            "pm2_5": {
                "value": 10.2,
                "unit": "µg/m³",
                "business_time": "2026-08-28T17:00:00+08:00",
                "spatial_scale": "1km_grid_estimate",
                "reliability": 0.72,
            }
        }
    )

    assert "ug/m3" in text
    text.encode("gbk")


def test_cli_subprocess_emits_utf8_text() -> None:
    executable_name = (
        "evaluation-model-qwen.exe" if sys.platform == "win32" else "evaluation-model-qwen"
    )
    executable = Path(sys.executable).with_name(executable_name)

    completed = subprocess.run(
        [str(executable), "--help"],
        check=True,
        capture_output=True,
    )

    assert "徐汇健康路线" in completed.stdout.decode("utf-8")
