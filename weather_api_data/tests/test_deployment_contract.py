from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
WINDOWS_SCRIPT = ROOT / "weather_api_data" / "scripts" / "install_windows_tasks.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "environment-refresh.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_tasks_use_frozen_cli_contract_and_runtime_paths() -> None:
    script = _read(WINDOWS_SCRIPT)

    assert '[ValidateSet("Install", "Status", "Uninstall")]' in script
    assert "[IO.Path]::IsPathRooted($WeatherRoot)" in script
    assert '$WeatherRoot -match "^[A-Za-z]:[^\\\\/]"' in script
    assert ".venv\\Scripts\\weather-api-data.exe" in script
    assert "-WorkingDirectory $resolvedRoot" in script
    for tier in ("weather", "hourly", "daily"):
        command = f'--root `"$resolvedRoot`" scheduled-refresh --tier {tier}'
        assert command in script


def test_windows_task_triggers_and_reliability_settings_are_explicit() -> None:
    script = _read(WINDOWS_SCRIPT)

    assert "New-TimeSpan -Minutes 15" in script
    assert "New-TimeSpan -Hours 1" in script
    assert re.search(r'New-ScheduledTaskTrigger -Daily -At ["\']06:07["\']', script)
    assert "-StartWhenAvailable" in script
    assert "-RestartCount 3" in script
    assert "-RestartInterval (New-TimeSpan -Minutes 5)" in script
    assert "-MultipleInstances IgnoreNew" in script


def test_windows_status_is_read_only_and_uninstall_targets_exact_names() -> None:
    script = _read(WINDOWS_SCRIPT)
    expected_names = {
        "XuhuiEnvironmentRefresh-Weather",
        "XuhuiEnvironmentRefresh-Hourly",
        "XuhuiEnvironmentRefresh-Daily",
    }

    assert "SupportsShouldProcess = $true" in script
    assert "Get-ScheduledTask -TaskName $definition.Name" in script
    assert "Get-ScheduledTaskInfo -TaskName $definition.Name" in script
    assert "Unregister-ScheduledTask -TaskName $definition.Name" in script
    assert "Unregister-ScheduledTask -TaskName *" not in script
    assert expected_names <= set(re.findall(r"XuhuiEnvironmentRefresh-[A-Za-z]+", script))


def test_workflow_is_manual_only_and_exposes_tier_choice() -> None:
    workflow = _read(WORKFLOW)

    assert "workflow_dispatch:" in workflow
    assert not re.search(r"^\s*schedule\s*:", workflow, flags=re.MULTILINE)
    assert "type: choice" in workflow
    for tier in ("weather", "hourly", "daily"):
        assert re.search(rf"^\s+- {tier}$", workflow, flags=re.MULTILINE)
    assert "deploy_pages:" in workflow
    assert "default: false" in workflow


def test_workflow_reads_secrets_as_environment_without_writing_env_file() -> None:
    workflow = _read(WORKFLOW)

    for secret in (
        "QWEATHER_API_KEY",
        "QWEATHER_API_HOST",
        "POLLEN_API_KEY",
        "SHANGHAI_NOISE_TOKEN",
    ):
        assert f"${{{{ secrets.{secret} }}}}" in workflow
    assert not re.search(r"(?:echo|printf|Out-File|Set-Content).*(?:\.env|GITHUB_ENV)", workflow)


def test_workflow_uses_frozen_uv_and_uploads_pages_tree() -> None:
    workflow = _read(WORKFLOW)

    assert "uv sync --directory weather_api_data --frozen --extra chap" in workflow
    assert re.search(
        r'weather-api-data --root "\$GITHUB_WORKSPACE/weather_api_data"\s+'
        r'scheduled-refresh --tier "\$\{\{ inputs\.tier \}\}"',
        workflow,
    )
    assert "uses: actions/upload-pages-artifact@" in workflow
    assert "path: pages-artifact" in workflow
    assert "web/index.html" in workflow
    assert "data/web/environment_dashboard.json" in workflow
    assert "if: ${{ inputs.deploy_pages }}" in workflow
    assert "uses: actions/deploy-pages@" in workflow
