from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

import weather_api_data.scheduler as scheduler
from weather_api_data.scheduler import run_scheduled_refresh

NOW = datetime(2026, 8, 27, 1, 2, 3, tzinfo=timezone.utc)


def test_windows_weather_task_runs_every_five_minutes() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "install_windows_tasks.ps1"
    script = script_path.read_text(encoding="utf-8-sig")

    assert 'Description = "Refresh Xuhui weather and alerts every 5 minutes"' in script
    assert "$start = $start.AddMinutes(5)" in script
    assert "-RepetitionInterval (New-TimeSpan -Minutes 5)" in script


def _callback(
    name: str,
    calls: list[str],
    result: Mapping[str, object],
) -> Callable[[], Mapping[str, object]]:
    def invoke() -> Mapping[str, object]:
        calls.append(name)
        return result

    return invoke


@pytest.mark.parametrize(
    ("tier", "expected_call"),
    [("weather", "weather"), ("hourly", "hourly"), ("daily", "daily")],
)
def test_scheduled_refresh_dispatches_one_tier_then_publishes(
    tmp_path: Path,
    tier: str,
    expected_call: str,
) -> None:
    calls: list[str] = []
    result = run_scheduled_refresh(
        tier=tier,
        runtime_dir=tmp_path / "runtime",
        weather_refresh=_callback("weather", calls, {"status": "ok"}),
        hourly_refresh=_callback("hourly", calls, {"status": "ok"}),
        daily_refresh=_callback("daily", calls, {"status": "ok"}),
        publish=_callback("publish", calls, {"status": "ok", "output": "dashboard.json"}),
        now_fn=lambda: NOW,
    )

    assert calls == [expected_call, "publish"]
    assert result["status"] == "ok"
    assert result["tier"] == tier
    assert result["refresh"] == {"status": "ok"}
    assert result["publish"] == {"status": "ok", "output": "dashboard.json"}

    state = json.loads((tmp_path / "runtime" / "scheduler_state.json").read_text("utf-8"))
    assert state == {
        "error": None,
        "last_attempt": NOW.isoformat(),
        "last_success": NOW.isoformat(),
        "status": "ok",
        "tier": tier,
    }
    assert not (tmp_path / "runtime" / "scheduled_refresh.lock").exists()


def test_partial_refresh_is_usable_and_updates_last_success(tmp_path: Path) -> None:
    calls: list[str] = []
    result = run_scheduled_refresh(
        tier="hourly",
        runtime_dir=tmp_path / "runtime",
        weather_refresh=_callback("weather", calls, {"status": "ok"}),
        hourly_refresh=_callback(
            "hourly",
            calls,
            {"status": "partial", "pm25_forecast_status": "partial"},
        ),
        daily_refresh=_callback("daily", calls, {"status": "ok"}),
        publish=_callback("publish", calls, {"status": "ok"}),
        now_fn=lambda: NOW,
    )

    assert result["status"] == "partial"
    state = json.loads((tmp_path / "runtime" / "scheduler_state.json").read_text("utf-8"))
    assert state["last_success"] == NOW.isoformat()
    assert state["error"] is None


def test_existing_lock_blocks_callbacks_and_records_locked_attempt(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    active_lock = {
        "created_at": NOW.isoformat(),
        "pid": 12345,
        "tier": "daily",
        "token": "active",
    }
    (runtime_dir / "scheduled_refresh.lock").write_text(
        json.dumps(active_lock),
        encoding="utf-8",
    )
    calls: list[str] = []

    result = run_scheduled_refresh(
        tier="daily",
        runtime_dir=runtime_dir,
        weather_refresh=_callback("weather", calls, {"status": "ok"}),
        hourly_refresh=_callback("hourly", calls, {"status": "ok"}),
        daily_refresh=_callback("daily", calls, {"status": "ok"}),
        publish=_callback("publish", calls, {"status": "ok"}),
        now_fn=lambda: NOW,
    )

    assert calls == []
    assert result["status"] == "locked"
    state = json.loads((runtime_dir / "scheduler_state.json").read_text("utf-8"))
    assert state["status"] == "locked"
    assert state["error"] == {
        "message": "已有调度刷新正在运行",
        "stage": "lock",
        "type": "SchedulerLockedError",
    }
    lock = json.loads((runtime_dir / "scheduled_refresh.lock").read_text("utf-8"))
    assert lock == active_lock


def test_stale_lock_is_atomically_isolated_before_refresh(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    stale_lock = {
        "created_at": (NOW - timedelta(hours=2)).isoformat(),
        "pid": 99999,
        "tier": "weather",
        "token": "abandoned",
    }
    (runtime_dir / "scheduled_refresh.lock").write_text(
        json.dumps(stale_lock),
        encoding="utf-8",
    )
    calls: list[str] = []

    result = run_scheduled_refresh(
        tier="hourly",
        runtime_dir=runtime_dir,
        weather_refresh=_callback("weather", calls, {"status": "ok"}),
        hourly_refresh=_callback("hourly", calls, {"status": "ok"}),
        daily_refresh=_callback("daily", calls, {"status": "ok"}),
        publish=_callback("publish", calls, {"status": "ok"}),
        now_fn=lambda: NOW,
    )

    assert result["status"] == "ok"
    assert calls == ["hourly", "publish"]
    isolated = list(runtime_dir.glob(".scheduled_refresh.lock.*.stale"))
    assert len(isolated) == 1
    assert json.loads(isolated[0].read_text("utf-8")) == stale_lock
    assert not (runtime_dir / "scheduled_refresh.lock").exists()


def test_refresh_exception_still_publishes_available_previous_snapshot(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail_refresh() -> Mapping[str, object]:
        calls.append("weather")
        raise RuntimeError("weather endpoint unavailable")

    result = run_scheduled_refresh(
        tier="weather",
        runtime_dir=tmp_path / "runtime",
        weather_refresh=fail_refresh,
        hourly_refresh=_callback("hourly", calls, {"status": "ok"}),
        daily_refresh=_callback("daily", calls, {"status": "ok"}),
        publish=_callback("publish", calls, {"status": "stale", "available": True}),
        now_fn=lambda: NOW,
    )

    assert calls == ["weather", "publish"]
    assert result["status"] == "partial"
    assert result["publish"] == {"status": "stale", "available": True}
    error = cast(dict[str, object], result["error"])
    assert error == {
        "message": "weather endpoint unavailable",
        "stage": "refresh",
        "type": "RuntimeError",
    }
    state = json.loads((tmp_path / "runtime" / "scheduler_state.json").read_text("utf-8"))
    assert state["last_success"] is None
    assert state["status"] == "partial"


@pytest.mark.parametrize(
    "publish_result",
    [{"status": "no_data"}, {"status": "error"}, {}],
)
def test_failed_refresh_is_fatal_when_publish_has_no_usable_snapshot(
    tmp_path: Path,
    publish_result: Mapping[str, object],
) -> None:
    def fail_refresh() -> Mapping[str, object]:
        raise ValueError("refresh failed")

    result = run_scheduled_refresh(
        tier="daily",
        runtime_dir=tmp_path / "runtime",
        weather_refresh=lambda: {"status": "ok"},
        hourly_refresh=lambda: {"status": "ok"},
        daily_refresh=fail_refresh,
        publish=lambda: publish_result,
        now_fn=lambda: NOW,
    )

    assert result["status"] == "fatal"
    error = cast(dict[str, object], result["error"])
    assert error["stage"] == "publish"
    refresh_error = cast(dict[str, object], error["refresh_error"])
    assert refresh_error["stage"] == "refresh"
    assert refresh_error["type"] == "ValueError"


def test_publish_exception_is_fatal_and_lock_is_released(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"

    def fail_publish() -> Mapping[str, object]:
        raise OSError("disk full")

    result = run_scheduled_refresh(
        tier="weather",
        runtime_dir=runtime_dir,
        weather_refresh=lambda: {"status": "ok"},
        hourly_refresh=lambda: {"status": "ok"},
        daily_refresh=lambda: {"status": "ok"},
        publish=fail_publish,
        now_fn=lambda: NOW,
    )

    assert result["status"] == "fatal"
    assert cast(dict[str, object], result["error"])["stage"] == "publish"
    assert not (runtime_dir / "scheduled_refresh.lock").exists()


def test_failed_attempt_preserves_previous_last_success(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    previous_success = "2026-08-26T00:00:00+00:00"
    (runtime_dir / "scheduler_state.json").write_text(
        json.dumps(
            {
                "last_attempt": previous_success,
                "last_success": previous_success,
                "status": "ok",
                "tier": "weather",
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    result = run_scheduled_refresh(
        tier="hourly",
        runtime_dir=runtime_dir,
        weather_refresh=lambda: {"status": "ok"},
        hourly_refresh=lambda: {"status": "error"},
        daily_refresh=lambda: {"status": "ok"},
        publish=lambda: {"status": "stale"},
        now_fn=lambda: NOW,
    )

    assert result["status"] == "partial"
    state = json.loads((runtime_dir / "scheduler_state.json").read_text("utf-8"))
    assert state["last_success"] == previous_success
    assert cast(dict[str, object], state["error"])["stage"] == "refresh"


def test_corrupt_state_is_fatal_and_skips_callbacks(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "scheduler_state.json").write_text("{broken", encoding="utf-8")
    calls: list[str] = []

    result = run_scheduled_refresh(
        tier="weather",
        runtime_dir=runtime_dir,
        weather_refresh=_callback("weather", calls, {"status": "ok"}),
        hourly_refresh=_callback("hourly", calls, {"status": "ok"}),
        daily_refresh=_callback("daily", calls, {"status": "ok"}),
        publish=_callback("publish", calls, {"status": "ok"}),
        now_fn=lambda: NOW,
    )

    assert result["status"] == "fatal"
    assert calls == []
    state = json.loads((runtime_dir / "scheduler_state.json").read_text("utf-8"))
    assert state["status"] == "fatal"
    assert cast(dict[str, object], state["error"])["stage"] == "state"
    assert not (runtime_dir / "scheduled_refresh.lock").exists()


def test_scheduler_state_uses_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destinations: list[Path] = []
    real_replace = scheduler.os.replace

    def record_replace(source: str | Path, destination: str | Path) -> None:
        destinations.append(Path(destination))
        real_replace(source, destination)

    monkeypatch.setattr(scheduler.os, "replace", record_replace)
    runtime_dir = tmp_path / "runtime"
    result = run_scheduled_refresh(
        tier="daily",
        runtime_dir=runtime_dir,
        weather_refresh=lambda: {"status": "ok"},
        hourly_refresh=lambda: {"status": "ok"},
        daily_refresh=lambda: {"status": "ok"},
        publish=lambda: {"status": "ok"},
        now_fn=lambda: NOW,
    )

    assert result["status"] == "ok"
    assert runtime_dir / "scheduler_state.json" in destinations
    assert not list(runtime_dir.glob(".scheduler_state.json.*.tmp"))


def test_invalid_tier_fails_before_creating_runtime_files(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"

    with pytest.raises(ValueError, match="tier"):
        run_scheduled_refresh(
            tier="weekly",
            runtime_dir=runtime_dir,
            weather_refresh=lambda: {"status": "ok"},
            hourly_refresh=lambda: {"status": "ok"},
            daily_refresh=lambda: {"status": "ok"},
            publish=lambda: {"status": "ok"},
        )

    assert not runtime_dir.exists()
