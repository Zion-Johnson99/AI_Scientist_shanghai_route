"""Unit tests for weather_api_data.web_export module.

Verifies:
- Output structure (top-level keys: metadata, current, forecast, routes)
- 90 route items coverage
- Required semantic fields per route item
- Graceful handling of missing/partial data
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from weather_api_data.web_export import (
    build_dashboard,
    validate_dashboard,
    DashboardValidationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_route_env(route_id: str, *, complete: bool = True) -> dict[str, Any]:
    """Build a single route environment record."""
    record: dict[str, Any] = {
        "route_id": route_id,
        "pm2_5": {
            "value": 35.0,
            "unit": "ug/m3",
            "estimated": True,
            "status": "ok",
            "confidence": 0.75,
        },
        "noise": {
            "value": 55,
            "unit": "risk_index_0_100",
            "estimated": True,
            "status": "ok",
            "confidence": 0.6,
        },
        "pollen_daily": {
            "value": 42,
            "unit": "grains/m3_proxy",
            "estimated": True,
            "status": "ok",
            "confidence": 0.5,
        },
    }
    if not complete:
        del record["pollen_daily"]
    return record


def _make_route_ids(count: int = 90) -> list[str]:
    """Generate route IDs matching the catalog convention."""
    modes = ["walk", "run", "bike"]
    ids: list[str] = []
    for mode in modes:
        for i in range(1, count // 3 + 1):
            ids.append(f"{mode}_{i:03d}")
    return ids[:count]


def _make_pipeline_result(
    route_ids: list[str] | None = None,
    *,
    complete: bool = True,
    status: str = "ok",
) -> dict[str, Any]:
    """Build a minimal pipeline result dict consumed by build_dashboard."""
    if route_ids is None:
        route_ids = _make_route_ids(90)

    now_iso = datetime.now(timezone.utc).isoformat()

    routes_items = [_make_route_env(rid, complete=complete) for rid in route_ids]

    return {
        "generated_at": now_iso,
        "status": status,
        "weather": {
            "temperature_c": 22.0,
            "humidity_pct": 65,
            "wind_speed_ms": 3.2,
            "precipitation_mm": 0.0,
            "condition": "partly_cloudy",
        },
        "aqi": {
            "value": 72,
            "primary_pollutant": "PM2.5",
            "status": "ok",
        },
        "routes": routes_items,
    }


@pytest.fixture()
def pipeline_result_full() -> dict[str, Any]:
    return _make_pipeline_result()


@pytest.fixture()
def pipeline_result_partial() -> dict[str, Any]:
    return _make_pipeline_result(complete=False)


@pytest.fixture()
def pipeline_result_few_routes() -> dict[str, Any]:
    return _make_pipeline_result(route_ids=_make_route_ids(10))


# ---------------------------------------------------------------------------
# Tests: build_dashboard structure
# ---------------------------------------------------------------------------


class TestBuildDashboardStructure:
    """Verify top-level structure of the dashboard output."""

    def test_top_level_keys_present(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        assert "metadata" in dashboard
        assert "current" in dashboard
        assert "forecast" in dashboard
        assert "routes" in dashboard

    def test_metadata_contains_generated_at(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        assert "generated_at" in dashboard["metadata"]
        # Must be parseable as ISO datetime
        datetime.fromisoformat(dashboard["metadata"]["generated_at"])

    def test_metadata_contains_status(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        assert "status" in dashboard["metadata"]
        assert dashboard["metadata"]["status"] in ("ok", "partial", "stale", "error", "no_data")

    def test_metadata_contains_sources(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        assert "sources" in dashboard["metadata"]

    def test_current_contains_weather_summary(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        current = dashboard["current"]
        assert "temperature_c" in current
        assert "humidity_pct" in current
        assert "wind_speed_ms" in current

    def test_forecast_is_list(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        assert isinstance(dashboard["forecast"], list)


# ---------------------------------------------------------------------------
# Tests: routes coverage
# ---------------------------------------------------------------------------


class TestRoutesCoverage:
    """Verify routes section covers 90 items with correct structure."""

    def test_routes_items_count_90(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        assert len(dashboard["routes"]["items"]) == 90

    def test_routes_items_have_route_id(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            assert "route_id" in item
            assert isinstance(item["route_id"], str)
            assert len(item["route_id"]) > 0

    def test_route_ids_unique(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        ids = [item["route_id"] for item in dashboard["routes"]["items"]]
        assert len(ids) == len(set(ids))

    def test_route_ids_match_input(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        expected_ids = set(_make_route_ids(90))
        actual_ids = {item["route_id"] for item in dashboard["routes"]["items"]}
        assert actual_ids == expected_ids

    def test_fewer_routes_raises_or_marks_partial(
        self, pipeline_result_few_routes: dict[str, Any]
    ) -> None:
        """When fewer than 90 routes, build_dashboard should either raise or mark partial."""
        dashboard = build_dashboard(pipeline_result_few_routes)
        # Accept either: metadata status is partial, or routes count < 90 is flagged
        if dashboard["metadata"]["status"] == "ok":
            # If status is ok, it must still have the correct count
            pytest.fail("Expected partial status when fewer than 90 routes provided")
        assert dashboard["metadata"]["status"] in ("partial", "error")


# ---------------------------------------------------------------------------
# Tests: semantic fields per route item
# ---------------------------------------------------------------------------


class TestSemanticFields:
    """Verify each route item contains required semantic fields."""

    REQUIRED_ENV_KEYS = ("pm2_5", "noise", "pollen_daily")
    REQUIRED_SEMANTIC_FIELDS = ("value", "unit", "estimated", "status")

    def test_all_env_keys_present(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            for key in self.REQUIRED_ENV_KEYS:
                assert key in item, f"Missing key '{key}' in route {item['route_id']}"

    def test_semantic_fields_per_env_block(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            for key in self.REQUIRED_ENV_KEYS:
                block = item[key]
                for field in self.REQUIRED_SEMANTIC_FIELDS:
                    assert field in block, (
                        f"Missing semantic field '{field}' in "
                        f"route {item['route_id']}.{key}"
                    )

    def test_pm25_unit_is_ug_m3(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            assert item["pm2_5"]["unit"] == "ug/m3"

    def test_noise_unit_is_risk_index(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            assert item["noise"]["unit"] == "risk_index_0_100"

    def test_estimated_is_boolean(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            for key in self.REQUIRED_ENV_KEYS:
                assert isinstance(item[key]["estimated"], bool)

    def test_status_in_enum(self, pipeline_result_full: dict[str, Any]) -> None:
        valid_statuses = {"ok", "stale", "estimated", "partial", "error", "no_data"}
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            for key in self.REQUIRED_ENV_KEYS:
                assert item[key]["status"] in valid_statuses

    def test_confidence_present_and_numeric(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        for item in dashboard["routes"]["items"]:
            for key in self.REQUIRED_ENV_KEYS:
                block = item[key]
                if "confidence" in block:
                    assert isinstance(block["confidence"], (int, float))
                    assert 0.0 <= block["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Tests: partial / missing data handling
# ---------------------------------------------------------------------------


class TestPartialData:
    """Verify graceful handling when data is incomplete."""

    def test_partial_marks_missing_fields(self, pipeline_result_partial: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_partial)
        # When pollen_daily is missing from input, output should mark it
        for item in dashboard["routes"]["items"]:
            if "pollen_daily" not in item:
                # Acceptable: field absent but metadata status is partial
                assert dashboard["metadata"]["status"] in ("partial", "stale")
            else:
                # If present, must have semantic fields
                assert "value" in item["pollen_daily"]

    def test_empty_routes_list(self) -> None:
        result = _make_pipeline_result(route_ids=[])
        dashboard = build_dashboard(result)
        assert dashboard["metadata"]["status"] in ("partial", "error", "no_data")
        assert len(dashboard["routes"]["items"]) == 0

    def test_status_error_propagates(self) -> None:
        result = _make_pipeline_result(status="error")
        dashboard = build_dashboard(result)
        assert dashboard["metadata"]["status"] == "error"


# ---------------------------------------------------------------------------
# Tests: validate_dashboard
# ---------------------------------------------------------------------------


class TestValidateDashboard:
    """Verify the validation function catches structural issues."""

    def test_valid_dashboard_passes(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        # Should not raise
        validate_dashboard(dashboard)

    def test_missing_top_level_key_fails(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        del dashboard["routes"]
        with pytest.raises(DashboardValidationError, match="routes"):
            validate_dashboard(dashboard)

    def test_wrong_route_count_fails(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        dashboard["routes"]["items"] = dashboard["routes"]["items"][:50]
        with pytest.raises(DashboardValidationError):
            validate_dashboard(dashboard, expected_route_count=90)

    def test_missing_semantic_field_fails(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        # Remove a required semantic field from first item
        del dashboard["routes"]["items"][0]["pm2_5"]["unit"]
        with pytest.raises(DashboardValidationError):
            validate_dashboard(dashboard)

    def test_no_sensitive_fields_in_output(self, pipeline_result_full: dict[str, Any]) -> None:
        """Ensure no absolute paths or keys leak into the dashboard."""
        dashboard = build_dashboard(pipeline_result_full)
        raw = json.dumps(dashboard)
        # No absolute paths (Windows or Unix)
        assert "C:\\" not in raw
        assert "/home/" not in raw
        assert "/Users/" not in raw
        # No API key patterns
        assert "api_key" not in raw.lower() or "api_key" in ("", "")
        assert "Authorization" not in raw


# ---------------------------------------------------------------------------
# Tests: JSON serializability
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify output is JSON-serializable for file export."""

    def test_json_roundtrip(self, pipeline_result_full: dict[str, Any]) -> None:
        dashboard = build_dashboard(pipeline_result_full)
        serialized = json.dumps(dashboard, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized["metadata"]["generated_at"] == dashboard["metadata"]["generated_at"]
        assert len(deserialized["routes"]["items"]) == 90

    def test_no_datetime_objects_in_output(self, pipeline_result_full: dict[str, Any]) -> None:
        """All datetime values must be serialized as ISO strings."""
        dashboard = build_dashboard(pipeline_result_full)

        def check_no_datetime(obj: Any, path: str = "root") -> None:
            if isinstance(obj, datetime):
                pytest.fail(f"Found datetime object at {path}")
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    check_no_datetime(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    check_no_datetime(v, f"{path}[{i}]")

        check_no_datetime(dashboard)
