from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from weather_api_data import cli


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def probe_standard(self, point_id: str, *, confirmed: bool) -> dict[str, object]:
        self.calls.append(("probe_standard", (point_id, confirmed)))
        return {"status": "ok", "call_count": 1}

    def probe_advanced(self, point_id: str) -> dict[str, object]:
        self.calls.append(("probe_advanced", point_id))
        return {"status": "ok", "call_count": 2}

    def probe_qweather(self, point_id: str) -> dict[str, object]:
        self.calls.append(("probe_qweather", point_id))
        return {"status": "ok", "call_count": 2}

    def validate_point(self, point_id: str) -> dict[str, object]:
        self.calls.append(("validate_point", point_id))
        return {"status": "ok", "call_count": 6}

    def discover(self) -> dict[str, object]:
        self.calls.append(("discover", None))
        return {"status": "ok", "call_count": 28}

    def refresh(self) -> dict[str, object]:
        self.calls.append(("refresh", None))
        return {"status": "ok", "call_count": 28, "air_quality_zone_count": 11}

    def refresh_weather(self) -> dict[str, object]:
        self.calls.append(("refresh_weather", None))
        return {"status": "ok", "call_count": 3}

    def backfill(self, *, year: int, month: int) -> dict[str, object]:
        self.calls.append(("backfill", (year, month)))
        return {"status": "partial", "year": year, "month": month}

    def export(self) -> dict[str, Path]:
        self.calls.append(("export", None))
        return {"run_report.json": Path("runtime/exports/run_report.json")}

    def prune_history(self, *, cutoff: Any, apply: bool) -> dict[str, object]:
        self.calls.append(("prune_history", (cutoff, apply)))
        return {"status": "ok", "apply": apply}


class FakeRuntime:
    def __init__(self) -> None:
        self.pipeline = FakePipeline()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def write_env(path: Path, *, history_enabled: bool = True) -> None:
    path.write_text(
        "\n".join(
            (
                "WEATHERCN_ADVANCED_API_KEY=fake-api-key",
                "WEATHERCN_ADVANCED_SECRET=fake-secret",
                "WEATHERCN_ADVANCED_ENV=test",
                "WEATHERCN_ADVANCED_BASE_URL=https://apidev.weathercn.com",
                "WEATHERCN_STANDARD_ENABLED=false",
                f"WEATHER_HISTORY_ENABLED={'true' if history_enabled else 'false'}",
            )
        ),
        encoding="utf-8",
    )


def test_config_check_validates_local_layout_without_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)

    exit_code = cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "config-check"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["status"] == "partial"
    assert output["weather_provider"] == "qweather"
    assert output["qweather_ready"] is False
    assert output["qweather_missing"] == ["QWEATHER_API_KEY", "QWEATHER_API_HOST"]
    assert "advanced_base_url" not in output
    assert output["history_enabled"] is True
    assert output["pollen_enabled"] is False
    assert output["pollen_hard_limit_per_run"] == 60
    assert output["shanghai_noise_enabled"] is False
    assert output["shanghai_noise_ready"] is False
    assert output["shanghai_noise_hard_limit_per_run"] == 4
    rendered = json.dumps(output)
    assert "fake-api-key" not in rendered
    assert "fake-secret" not in rendered
    assert not (tmp_path / "runtime").exists()


def test_dry_run_reports_locked_worst_case_budgets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)

    assert cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "dry-run"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["sampling_point_count"] == 16
    assert output["air_quality_zone_count"] == 11
    assert output["air_quality_strategy_counts"] == {
        "qweather_direct": 6,
        "district_blend": 3,
        "shanghai_station": 2,
    }
    assert output["refresh_station_requests"] == 4
    assert output["estimated_calls"] == {
        "probe-qweather": 2,
        "probe-standard": 1,
        "validate-point": 6,
        "discover": 0,
        "refresh-weather": 3,
        "refresh": 28,
        "refresh-all-qweather": 28,
        "refresh-all-pollen": 54,
        "probe-pollen": 1,
        "refresh-pollen-grid": 54,
        "probe-noise": 1,
        "refresh-noise": 4,
    }
    assert output["qweather_hard_limit_per_run"] == 80
    assert output["refresh_retry_headroom"] == 52
    assert output["hard_limit_behavior"] == "stop_before_attempt_81"
    assert "historical_pm2_5_2025" not in output


@pytest.mark.parametrize(
    ("arguments", "expected_call"),
    [
        pytest.param(
            ["probe-standard", "--confirm-standard-probe"],
            "probe_standard",
            marks=pytest.mark.skip(reason="普通 Key 已迁移到独立运行时，见专属测试"),
        ),
        pytest.param(
            ["probe-advanced"],
            "probe_advanced",
            marks=pytest.mark.skip(reason="保留旧华风测试代码，生产命令已删除"),
        ),
        (["probe-qweather", "--confirm-qweather-probe"], "probe_qweather"),
        (["validate-point", "--point-id", "XH_ENT_0002"], "validate_point"),
        (["discover"], "discover"),
        (["refresh-weather"], "refresh_weather"),
        pytest.param(
            ["backfill", "--year", "2025", "--month", "2025-08"],
            "backfill",
            marks=pytest.mark.skip(reason="保留旧华风测试代码，生产命令已删除"),
        ),
        (["export"], "export"),
        (["prune-history", "--dry-run"], "prune_history"),
        (["prune-history", "--apply"], "prune_history"),
    ],
)
def test_network_and_storage_commands_dispatch_once_and_close_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    expected_call: str,
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    runtime = FakeRuntime()

    def fake_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        return runtime

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)

    exit_code = cli.main(["--root", str(tmp_path), "--env-file", str(env_file), *arguments])

    assert exit_code == 0
    assert runtime.closed is True
    assert runtime.pipeline.calls[0][0] == expected_call
    assert json.loads(capsys.readouterr().out)["status"] in {"ok", "partial"}


def test_probe_standard_requires_explicit_confirmation(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    with pytest.raises(SystemExit) as captured:
        cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "probe-standard"])
    assert captured.value.code == 2


def test_probe_standard_uses_independent_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    calls: list[tuple[Path, str, bool]] = []

    def fake_probe(*, settings: object, root: Path, point_id: str, confirmed: bool) -> object:
        del settings
        calls.append((root, point_id, confirmed))
        return {"status": "ok", "call_count": 1}

    def fail_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        raise AssertionError("普通 Key 探针不应创建和风主运行时")

    monkeypatch.setattr(cli, "_probe_standard_from_project", fake_probe)
    monkeypatch.setattr(cli, "build_runtime", fail_build_runtime)

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "probe-standard",
            "--confirm-standard-probe",
        ]
    )

    assert exit_code == 0
    assert calls == [(tmp_path.resolve(), "XH_ENT_0001", True)]
    assert json.loads(capsys.readouterr().out)["call_count"] == 1


@pytest.mark.skip(reason="保留旧华风回填测试代码，生产命令已删除")
def test_backfill_rejects_month_from_another_year(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    with pytest.raises(ValueError, match="year"):
        cli.main(
            [
                "--root",
                str(tmp_path),
                "--env-file",
                str(env_file),
                "backfill",
                "--year",
                "2025",
                "--month",
                "2024-12",
            ]
        )


def test_fuse_pm25_dispatches_local_fusion_without_network_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    calls: list[tuple[Path, str]] = []

    def fake_fuse(*, root: Path, target_time: Any) -> dict[str, object]:
        calls.append((root, target_time.isoformat()))
        return {"status": "ok", "grid_count": 54, "output_path": "pm25_grid_latest.json"}

    def fail_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        raise AssertionError("本地融合命令不应创建网络运行时")

    monkeypatch.setattr(cli, "fuse_pm25_from_local_sources", fake_fuse)
    monkeypatch.setattr(cli, "build_runtime", fail_build_runtime)

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "fuse-pm25",
            "--at",
            "2026-08-25T17:00:00+08:00",
        ]
    )

    assert exit_code == 0
    assert calls == [(tmp_path.resolve(), "2026-08-25T17:00:00+08:00")]
    assert json.loads(capsys.readouterr().out)["grid_count"] == 54


def test_refresh_automatically_fuses_latest_pm25_grid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    runtime = FakeRuntime()
    fusion_calls: list[Path] = []
    forecast_fusion_calls: list[Path] = []

    def fake_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        return runtime

    def fake_fuse_latest(*, root: Path) -> dict[str, object]:
        fusion_calls.append(root)
        return {
            "status": "ok",
            "target_time": "2026-08-25T18:00:00+08:00",
            "grid_count": 54,
            "output_path": "pm25_grid_latest.json",
        }

    def fake_fuse_forecast(*, root: Path) -> dict[str, object]:
        forecast_fusion_calls.append(root)
        return {
            "status": "ok",
            "forecast_count": 24,
            "grid_count": 54,
            "zone_count": 11,
            "output_path": "pm25_grid_forecast_24h.json",
        }

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(cli, "fuse_latest_pm25_from_local_sources", fake_fuse_latest)
    monkeypatch.setattr(
        cli,
        "fuse_pm25_forecast_from_local_sources",
        fake_fuse_forecast,
        raising=False,
    )

    exit_code = cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "refresh"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert runtime.closed is True
    assert runtime.pipeline.calls == [("refresh", None)]
    assert fusion_calls == [tmp_path.resolve()]
    assert forecast_fusion_calls == [tmp_path.resolve()]
    assert output["air_quality_zone_count"] == 11
    assert output["pm25_grid_fusion"]["grid_count"] == 54
    assert output["pm25_forecast_fusion"] == {
        "status": "ok",
        "forecast_count": 24,
        "grid_count": 54,
        "zone_count": 11,
        "output_path": "pm25_grid_forecast_24h.json",
    }


def test_refresh_all_runs_exposure_after_weather_and_pm25(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    runtime = FakeRuntime()
    exposure_calls: list[Path] = []

    def fake_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        return runtime

    def fake_fuse_latest(*, root: Path) -> dict[str, object]:
        return {"status": "ok", "grid_count": 54, "root": str(root)}

    def fake_fuse_forecast(*, root: Path) -> dict[str, object]:
        return {"status": "ok", "forecast_count": 24, "root": str(root)}

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(
        cli,
        "fuse_latest_pm25_from_local_sources",
        fake_fuse_latest,
    )
    monkeypatch.setattr(
        cli,
        "fuse_pm25_forecast_from_local_sources",
        fake_fuse_forecast,
    )

    def fake_exposure(*, settings: object, root: Path) -> dict[str, object]:
        del settings
        exposure_calls.append(root)
        return {
            "status": "partial",
            "pollen_grid_count": 54,
            "segment_count": 7366,
            "route_count": 90,
        }

    monkeypatch.setattr(cli, "refresh_exposure_from_project", fake_exposure)

    exit_code = cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "refresh-all"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert runtime.closed is True
    assert runtime.pipeline.calls == [("refresh", None)]
    assert exposure_calls == [tmp_path.resolve()]
    assert output["status"] == "partial"
    assert output["exposure"]["pollen_grid_count"] == 54
    assert output["exposure"]["route_count"] == 90


def test_publish_web_dispatches_without_network_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    calls: list[Path] = []

    def fake_publish(*, root: Path) -> dict[str, object]:
        calls.append(root)
        return {
            "status": "partial",
            "output_path": str(
                root.parent / "xuhui_route_builder/data/web/environment_dashboard.json"
            ),
            "generated_at": "2026-08-27T15:00:00+08:00",
            "grid_count": 54,
            "route_count": 90,
        }

    def fail_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        raise AssertionError("网页发布不创建网络运行时")

    monkeypatch.setattr(cli, "_publish_web_summary", fake_publish)
    monkeypatch.setattr(cli, "build_runtime", fail_build_runtime)

    exit_code = cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "publish-web"])

    assert exit_code == 0
    assert calls == [tmp_path.resolve()]
    assert json.loads(capsys.readouterr().out)["route_count"] == 90


@pytest.mark.parametrize(
    ("tier", "expected_pipeline_call", "expected_exposure_calls"),
    [
        ("weather", "refresh_weather", 0),
        ("hourly", "refresh", 0),
        ("daily", "refresh", 1),
    ],
)
def test_scheduled_refresh_dispatches_selected_tier_and_publishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tier: str,
    expected_pipeline_call: str,
    expected_exposure_calls: int,
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    runtime = FakeRuntime()
    exposure_calls: list[Path] = []
    publish_calls: list[Path] = []

    def fake_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        return runtime

    def fake_fuse_latest(*, root: Path) -> dict[str, object]:
        return {"status": "ok", "root": str(root), "grid_count": 54}

    def fake_fuse_forecast(*, root: Path) -> dict[str, object]:
        return {"status": "partial", "root": str(root)}

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(
        cli,
        "fuse_latest_pm25_from_local_sources",
        fake_fuse_latest,
    )
    monkeypatch.setattr(
        cli,
        "fuse_pm25_forecast_from_local_sources",
        fake_fuse_forecast,
    )

    def fake_exposure(*, settings: object, root: Path) -> dict[str, object]:
        del settings
        exposure_calls.append(root)
        return {"status": "partial", "route_count": 90}

    def fake_publish(*, root: Path) -> dict[str, object]:
        publish_calls.append(root)
        return {"status": "partial", "route_count": 90, "grid_count": 54}

    def immediate_scheduler(**kwargs: object) -> dict[str, object]:
        callback = cast(Callable[[], dict[str, object]], kwargs[f"{tier}_refresh"])
        publish = cast(Callable[[], dict[str, object]], kwargs["publish"])
        refresh_result = callback()
        publish_result = publish()
        return {
            "status": "partial",
            "tier": tier,
            "refresh": refresh_result,
            "publish": publish_result,
        }

    monkeypatch.setattr(cli, "refresh_exposure_from_project", fake_exposure)
    monkeypatch.setattr(cli, "_publish_web_summary", fake_publish)
    monkeypatch.setattr(cli, "run_scheduled_refresh", immediate_scheduler)

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "scheduled-refresh",
            "--tier",
            tier,
        ]
    )

    assert exit_code == 0
    assert runtime.closed is True
    assert runtime.pipeline.calls[0][0] == expected_pipeline_call
    assert len(exposure_calls) == expected_exposure_calls
    assert publish_calls == [tmp_path.resolve()]
    assert json.loads(capsys.readouterr().out)["tier"] == tier


def test_refresh_preserves_successful_outputs_when_forecast_fusion_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    runtime = FakeRuntime()
    stale_forecast = tmp_path / "runtime" / "exports" / "pm25_grid_forecast_24h.json"
    stale_forecast.parent.mkdir(parents=True)
    stale_forecast.write_text('{"generated_at":"stale"}', encoding="utf-8")

    def fake_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        return runtime

    def fake_current_fusion(*, root: Path) -> dict[str, object]:
        return {
            "status": "ok",
            "grid_count": 54,
            "output_path": str(root / "runtime/exports/pm25_grid_latest.json"),
        }

    monkeypatch.setattr(cli, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(
        cli,
        "fuse_latest_pm25_from_local_sources",
        fake_current_fusion,
    )

    def fail_forecast(*, root: Path) -> dict[str, object]:
        del root
        raise cli.Pm25FusionError("和风逐小时空气质量缺少 PM2.5")

    monkeypatch.setattr(cli, "fuse_pm25_forecast_from_local_sources", fail_forecast)

    exit_code = cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "refresh"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["status"] == "partial"
    assert output["pm25_grid_fusion"]["status"] == "ok"
    forecast_result = output["pm25_forecast_fusion"]
    assert forecast_result["status"] == "error"
    assert forecast_result["error_type"] == "Pm25FusionError"
    assert forecast_result["message"] == "和风逐小时空气质量缺少 PM2.5"
    assert not stale_forecast.exists()
    quarantined = Path(forecast_result["stale_output_quarantined_to"])
    assert quarantined.parent == stale_forecast.parent / "stale"
    assert quarantined.read_text(encoding="utf-8") == '{"generated_at":"stale"}'


def test_probe_pollen_requires_explicit_confirmation(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)

    with pytest.raises(SystemExit) as captured:
        cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "probe-pollen"])

    assert captured.value.code == 2


def test_probe_noise_requires_explicit_confirmation(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)

    with pytest.raises(SystemExit) as captured:
        cli.main(["--root", str(tmp_path), "--env-file", str(env_file), "probe-noise"])

    assert captured.value.code == 2


def test_prepare_noise_data_dispatches_without_weather_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    calls: list[Path] = []

    def fake_prepare(root: Path) -> dict[str, object]:
        calls.append(root)
        return {"status": "ok", "observation_count": 2525}

    def fail_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        raise AssertionError("噪声数据准备命令不创建天气运行时")

    monkeypatch.setattr(cli, "prepare_noise_history_from_project", fake_prepare)
    monkeypatch.setattr(cli, "build_runtime", fail_build_runtime)

    exit_code = cli.main(
        ["--root", str(tmp_path), "--env-file", str(env_file), "prepare-noise-data"]
    )

    assert exit_code == 0
    assert calls == [tmp_path.resolve()]
    assert json.loads(capsys.readouterr().out)["observation_count"] == 2525


def test_pollen_probe_dispatches_without_weather_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    calls: list[tuple[Path, str, bool]] = []

    def fake_probe(
        *, settings: object, root: Path, grid_id: str, confirmed: bool
    ) -> dict[str, object]:
        del settings
        calls.append((root, grid_id, confirmed))
        return {"status": "ok", "grid_id": grid_id, "call_count": 1}

    def fail_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        raise AssertionError("花粉独立命令不应创建 WeatherCN 运行时")

    monkeypatch.setattr(cli, "probe_pollen_from_project", fake_probe)
    monkeypatch.setattr(cli, "build_runtime", fail_build_runtime)

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "probe-pollen",
            "--grid-id",
            "XH_PM25_G002",
            "--confirm-pollen-probe",
        ]
    )

    assert exit_code == 0
    assert calls == [(tmp_path.resolve(), "XH_PM25_G002", True)]
    assert json.loads(capsys.readouterr().out)["call_count"] == 1


@pytest.mark.parametrize(
    ("command", "function_name"),
    [
        ("refresh-exposure", "refresh_exposure_from_project"),
        ("build-static-exposure", "build_static_exposure_from_project"),
        ("build-noise", "build_noise_from_project"),
    ],
)
def test_exposure_commands_dispatch_without_weather_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    function_name: str,
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    calls: list[Path] = []

    def fake_command(**kwargs: object) -> dict[str, object]:
        calls.append(cast(Path, kwargs["root"]))
        return {"status": "partial", "route_count": 90}

    def fail_build_runtime(_settings: object, _root: Path) -> FakeRuntime:
        raise AssertionError("暴露独立命令不应创建 WeatherCN 运行时")

    monkeypatch.setattr(cli, function_name, fake_command)
    monkeypatch.setattr(cli, "build_runtime", fail_build_runtime)

    exit_code = cli.main(["--root", str(tmp_path), "--env-file", str(env_file), command])

    assert exit_code == 0
    assert calls == [tmp_path.resolve()]
    assert json.loads(capsys.readouterr().out)["route_count"] == 90


def test_static_exposure_passes_explicit_spatial_features_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file)
    spatial_path = tmp_path / "noise_features.geojson"
    received: dict[str, object] = {}

    def fake_build(**kwargs: object) -> dict[str, object]:
        received.update(kwargs)
        return {"status": "partial", "route_count": 90}

    monkeypatch.setattr(cli, "build_static_exposure_from_project", fake_build)

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "build-static-exposure",
            "--spatial-features",
            str(spatial_path),
        ]
    )

    assert exit_code == 0
    assert received == {
        "root": tmp_path.resolve(),
        "spatial_features_path": spatial_path,
    }


@pytest.mark.parametrize(
    "error",
    [TypeError("invalid exposure shape"), cli.SpatialFeatureError("invalid spatial feature")],
)
def test_console_main_converts_shape_errors_to_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    def fail_main() -> int:
        raise error

    monkeypatch.setattr(cli, "main", fail_main)

    assert cli.console_main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "error_type": type(error).__name__,
        "message": str(error),
    }


def test_print_json_is_safe_on_windows_gbk_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)

    print_json = cast(Callable[[object], None], getattr(cli, "_print_json"))
    print_json({"unit": "µg/m³", "name": "空气质量"})
    stdout.flush()

    assert json.loads(buffer.getvalue().decode("gbk")) == {
        "unit": "µg/m³",
        "name": "空气质量",
    }
