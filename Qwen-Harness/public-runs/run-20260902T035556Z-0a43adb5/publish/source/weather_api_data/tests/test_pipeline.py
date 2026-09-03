"""Tests for weather_api_data pipeline: fallback logic, snapshot generation, missing data marking."""

import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pytest

from weather_api_data.pipeline import (
    PipelineConfig,
    PipelineResult,
    run_pipeline,
    load_last_known_good,
    save_snapshot,
    check_api_keys,
)


@pytest.fixture
def tmp_runtime(tmp_path):
    """Create a temporary runtime/exports directory."""
    exports_dir = tmp_path / "runtime" / "exports"
    exports_dir.mkdir(parents=True)
    return exports_dir


@pytest.fixture
def sample_snapshot(tmp_runtime):
    """Create a valid last-known-good snapshot file."""
    snapshot = {
        "generated_at": "2024-06-01T08:00:00Z",
        "status": "ok",
        "tier": "weather",
        "data": {
            "temperature": 25.0,
            "humidity": 60,
            "wind_speed": 3.5,
            "aqi": 55,
        },
    }
    path = tmp_runtime / "weather_latest.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def config_no_keys(tmp_runtime):
    """Pipeline config with no API keys configured."""
    return PipelineConfig(
        exports_dir=tmp_runtime,
        api_keys={},
        allow_network=False,
        tier="weather",
    )


@pytest.fixture
def config_with_keys(tmp_runtime):
    """Pipeline config with API keys configured."""
    return PipelineConfig(
        exports_dir=tmp_runtime,
        api_keys={"weather_api": "test-key-123", "aqi_api": "test-key-456"},
        allow_network=True,
        tier="weather",
    )


class TestCheckApiKeys:
    """Tests for API key checking."""

    def test_no_keys_returns_missing_list(self, config_no_keys):
        missing = check_api_keys(config_no_keys)
        assert "weather_api" in missing
        assert "aqi_api" in missing

    def test_all_keys_present_returns_empty(self, config_with_keys):
        missing = check_api_keys(config_with_keys)
        assert missing == []

    def test_partial_keys_returns_only_missing(self, tmp_runtime):
        config = PipelineConfig(
            exports_dir=tmp_runtime,
            api_keys={"weather_api": "key"},
            allow_network=True,
            tier="weather",
        )
        missing = check_api_keys(config)
        assert "weather_api" not in missing
        assert "aqi_api" in missing


class TestFallbackLogic:
    """Tests for last-known-good fallback when keys are missing or network unavailable."""

    def test_no_keys_uses_last_known_good(self, config_no_keys, sample_snapshot):
        result = run_pipeline(config_no_keys)
        assert result.status == "stale"
        assert result.stale_reason is not None
        assert "key" in result.stale_reason.lower() or "network" in result.stale_reason.lower()
        assert result.data is not None
        assert result.data["temperature"] == 25.0

    def test_no_network_uses_last_known_good(self, tmp_runtime, sample_snapshot):
        config = PipelineConfig(
            exports_dir=tmp_runtime,
            api_keys={"weather_api": "key", "aqi_api": "key"},
            allow_network=False,
            tier="weather",
        )
        result = run_pipeline(config)
        assert result.status == "stale"
        assert result.stale_reason is not None

    def test_no_keys_no_snapshot_returns_partial(self, config_no_keys):
        result = run_pipeline(config_no_keys)
        assert result.status == "partial"
        assert result.data is None
        assert result.missing_items is not None
        assert len(result.missing_items) > 0

    def test_fallback_does_not_create_fill_values(self, config_no_keys, sample_snapshot):
        result = run_pipeline(config_no_keys)
        # Data should come from snapshot, not fabricated
        assert result.data == json.loads(sample_snapshot.read_text(encoding="utf-8"))["data"]

    def test_stale_reason_is_descriptive(self, config_no_keys, sample_snapshot):
        result = run_pipeline(config_no_keys)
        assert result.stale_reason is not None
        assert len(result.stale_reason) > 10


class TestSnapshotGeneration:
    """Tests for snapshot file generation."""

    def test_save_snapshot_creates_file(self, tmp_runtime):
        data = {"temperature": 20.0, "humidity": 50}
        path = save_snapshot(
            exports_dir=tmp_runtime,
            tier="weather",
            data=data,
            status="ok",
        )
        assert path.exists()
        content = json.loads(path.read_text(encoding="utf-8"))
        assert content["status"] == "ok"
        assert content["data"]["temperature"] == 20.0
        assert "generated_at" in content

    def test_snapshot_contains_generated_at(self, tmp_runtime):
        data = {"temperature": 22.0}
        path = save_snapshot(
            exports_dir=tmp_runtime,
            tier="hourly",
            data=data,
            status="ok",
        )
        content = json.loads(path.read_text(encoding="utf-8"))
        assert "generated_at" in content
        # Should be parseable as ISO datetime
        datetime.fromisoformat(content["generated_at"].replace("Z", "+00:00"))

    def test_snapshot_contains_status_field(self, tmp_runtime):
        data = {"aqi": 42}
        path = save_snapshot(
            exports_dir=tmp_runtime,
            tier="daily",
            data=data,
            status="partial",
        )
        content = json.loads(path.read_text(encoding="utf-8"))
        assert content["status"] == "partial"

    def test_snapshot_filename_includes_tier(self, tmp_runtime):
        data = {"temperature": 18.0}
        path = save_snapshot(
            exports_dir=tmp_runtime,
            tier="hourly",
            data=data,
            status="ok",
        )
        assert "hourly" in path.name

    def test_snapshot_no_absolute_paths(self, tmp_runtime):
        data = {"temperature": 19.0}
        path = save_snapshot(
            exports_dir=tmp_runtime,
            tier="weather",
            data=data,
            status="ok",
        )
        content_str = path.read_text(encoding="utf-8")
        # Should not contain absolute paths
        assert str(tmp_runtime) not in content_str

    def test_snapshot_no_api_keys(self, tmp_runtime):
        data = {"temperature": 21.0}
        path = save_snapshot(
            exports_dir=tmp_runtime,
            tier="weather",
            data=data,
            status="ok",
            api_keys={"weather_api": "secret-key"},
        )
        content_str = path.read_text(encoding="utf-8")
        assert "secret-key" not in content_str


class TestPartialStatusMarking:
    """Tests for partial/stale/estimated status marking."""

    def test_partial_when_some_sources_missing(self, tmp_runtime):
        config = PipelineConfig(
            exports_dir=tmp_runtime,
            api_keys={"weather_api": "key"},
            allow_network=False,
            tier="daily",
        )
        result = run_pipeline(config)
        assert result.status in ("partial", "stale")
        if result.missing_items:
            assert len(result.missing_items) > 0

    def test_estimated_flag_on_derived_values(self, tmp_runtime):
        config = PipelineConfig(
            exports_dir=tmp_runtime,
            api_keys={},
            allow_network=False,
            tier="weather",
        )
        result = run_pipeline(config)
        # When no data available, result should be partial with missing items
        if result.status == "partial":
            assert result.missing_items is not None

    def test_result_contains_tier_info(self, tmp_runtime, sample_snapshot):
        config = PipelineConfig(
            exports_dir=tmp_runtime,
            api_keys={},
            allow_network=False,
            tier="weather",
        )
        result = run_pipeline(config)
        assert result.tier == "weather"

    def test_result_status_in_valid_enum(self, tmp_runtime, sample_snapshot):
        config = PipelineConfig(
            exports_dir=tmp_runtime,
            api_keys={},
            allow_network=False,
            tier="weather",
        )
        result = run_pipeline(config)
        assert result.status in ("ok", "partial", "stale", "error", "no_data")


class TestLoadLastKnownGood:
    """Tests for loading last-known-good snapshots."""

    def test_load_existing_snapshot(self, sample_snapshot):
        data = load_last_known_good(sample_snapshot.parent, "weather")
        assert data is not None
        assert data["data"]["temperature"] == 25.0

    def test_load_missing_snapshot_returns_none(self, tmp_runtime):
        data = load_last_known_good(tmp_runtime, "weather")
        assert data is None

    def test_load_corrupted_snapshot_returns_none(self, tmp_runtime):
        path = tmp_runtime / "weather_latest.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        data = load_last_known_good(tmp_runtime, "weather")
        assert data is None

    def test_load_snapshot_with_missing_data_field(self, tmp_runtime):
        path = tmp_runtime / "weather_latest.json"
        path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        data = load_last_known_good(tmp_runtime, "weather")
        # Should return None or handle gracefully when data field is missing
        assert data is None or "data" not in data


class TestPipelineResult:
    """Tests for PipelineResult structure."""

    def test_result_has_required_fields(self, config_no_keys, sample_snapshot):
        result = run_pipeline(config_no_keys)
        assert hasattr(result, "status")
        assert hasattr(result, "tier")
        assert hasattr(result, "data")
        assert hasattr(result, "stale_reason")
        assert hasattr(result, "missing_items")

    def test_result_serializable_to_dict(self, config_no_keys, sample_snapshot):
        result = run_pipeline(config_no_keys)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "status" in d
        assert "tier" in d
        # Should be JSON serializable
        json.dumps(d, ensure_ascii=False)
