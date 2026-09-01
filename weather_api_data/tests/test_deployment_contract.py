from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
WINDOWS_SCRIPT = ROOT / "weather_api_data" / "scripts" / "install_windows_tasks.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "environment-refresh.yml"
PAGES_INDEX = ROOT / "xuhui_route_builder" / "pages-index.html"
WORKER_CONFIG = ROOT / "infra" / "cloudflare-environment-worker" / "wrangler.toml"


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

    assert "-RepetitionInterval (New-TimeSpan -Minutes 5)" in script
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


def test_workflow_schedules_backup_refresh_tiers_and_keeps_manual_choice() -> None:
    workflow = _read(WORKFLOW)

    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert 'cron: "10,25,40,55 * * * *"' in workflow
    assert 'cron: "5 * * * *"' in workflow
    assert 'cron: "7 22 * * *"' in workflow
    assert "type: choice" in workflow
    for tier in ("weather", "hourly", "daily"):
        assert re.search(rf"^\s+- {tier}$", workflow, flags=re.MULTILINE)
    assert "deploy_pages:" in workflow
    assert "default: true" in workflow


def test_workflow_routes_schedule_to_tier_and_persists_runtime() -> None:
    workflow = _read(WORKFLOW)

    assert "Resolve refresh tier" in workflow
    assert '"10,25,40,55 * * * *") tier="weather"' in workflow
    assert '"5 * * * *") tier="hourly"' in workflow
    assert '"7 22 * * *") tier="daily"' in workflow
    assert "uses: actions/cache/restore@" in workflow
    assert "uses: actions/cache/save@" in workflow
    assert "weather_api_data/runtime" in workflow
    assert "Bootstrap complete environment runtime" in workflow


def test_cloudflare_primary_schedule_uses_quarter_hours_and_watchdog() -> None:
    config = _read(WORKER_CONFIG)

    assert '"0,15,30,45 * * * *"' in config
    assert '"3,18,33,48 * * * *"' in config


def test_workflow_reads_secrets_as_environment_without_writing_env_file() -> None:
    workflow = _read(WORKFLOW)

    for secret in (
        "QWEATHER_API_KEY",
        "QWEATHER_API_HOST",
        "POLLEN_API_KEY",
        "SHANGHAI_NOISE_TOKEN",
        "AMAP_JS_API_KEY",
        "AMAP_JS_SECURITY_CODE",
        "TENCENT_SEARCH_KEY",
    ):
        assert f"${{{{ secrets.{secret} }}}}" in workflow
    assert "${{ vars.RECOMMENDATION_API_BASE_URL }}" in workflow
    assert "${{ vars.ENVIRONMENT_DASHBOARD_URL }}" in workflow
    assert "${{ secrets.ENVIRONMENT_PUBLISH_TOKEN }}" in workflow
    assert not re.search(r"(?:echo|printf|Out-File|Set-Content).*(?:\.env|GITHUB_ENV)", workflow)


def test_workflow_validates_and_publishes_last_known_good_dashboard() -> None:
    workflow = _read(WORKFLOW)

    assert "Validate online publish configuration" in workflow
    assert "Publish last-known-good environment dashboard" in workflow
    assert "Authorization: Bearer $ENVIRONMENT_PUBLISH_TOKEN" in workflow
    assert "--max-time 20" in workflow
    assert "--retry 2" in workflow
    assert "xuhui_route_builder/data/web/environment_dashboard.json" in workflow


def test_workflow_uses_frozen_uv_and_uploads_pages_tree() -> None:
    workflow = _read(WORKFLOW)

    assert "uv sync --directory weather_api_data --frozen --extra chap" in workflow
    assert re.search(
        r'weather-api-data --root "\$GITHUB_WORKSPACE/weather_api_data"\s+'
        r'scheduled-refresh --tier "\$\{\{ steps\.refresh-tier\.outputs\.tier \}\}"',
        workflow,
    )
    assert "uses: actions/upload-pages-artifact@" in workflow
    assert "path: pages-artifact" in workflow
    assert "xuhui_route_builder/pages-index.html" in workflow
    assert "pages-artifact/index.html" in workflow
    assert "web/index.html" in workflow
    assert "data/web/environment_dashboard.json" in workflow
    assert "Generate browser map configuration" in workflow
    assert "needs['refresh-and-build'].outputs.deploy_pages == 'true'" in workflow
    assert "uses: actions/deploy-pages@" in workflow


def test_workflow_only_builds_pages_artifact_for_explicit_page_deploys() -> None:
    workflow = _read(WORKFLOW)

    assert 'echo "deploy_pages=$deploy_pages" >> "$GITHUB_OUTPUT"' in workflow
    assert '"10,25,40,55 * * * *") tier="weather"; deploy_pages="false"' in workflow
    assert '"5 * * * *") tier="hourly"; deploy_pages="false"' in workflow
    assert '"7 22 * * *") tier="daily"; deploy_pages="true"' in workflow
    assert workflow.count(
        "if: ${{ steps.refresh-tier.outputs.deploy_pages == 'true' }}"
    ) == 3
    assert "deploy_pages: ${{ steps.refresh-tier.outputs.deploy_pages }}" in workflow
    assert "if: ${{ needs['refresh-and-build'].outputs.deploy_pages == 'true' }}" in workflow


def test_pages_root_redirects_to_web_application() -> None:
    html = _read(PAGES_INDEX)

    assert 'content="0; url=./web/"' in html
    assert 'location.replace("./web/")' in html
