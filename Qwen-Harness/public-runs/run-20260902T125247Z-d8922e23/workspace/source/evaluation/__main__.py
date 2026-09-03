"""Command-line entry: python -m evaluation [--serve] [--port N] [--score] [--metrics] [--selftest]."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import api
from .baselines import distance_only, shortest_access
from .metrics import build_case_requests, evaluate_matrix, run_matrix, score_case
from .recommend import (
    InvalidRequestError,
    _band_tables,
    load_default_inputs,
    recommend,
)
from .scorer import PROVENANCE, scored_catalog_summary
from .weights import DIMENSIONS, load_weights

logger = logging.getLogger("evaluation.main")

FIXTURE_TS = "2026-09-02T12:00:00+00:00"
SPORTS: tuple[str, ...] = ("walk", "run", "bike")


def _fx_exposure(values: dict[str, tuple[float | None, str]]) -> dict[str, Any]:
    units = {
        "pm25_ug_m3": "ug/m3",
        "aqi_us": "aqi",
        "noise_proxy_db": "dB",
        "traffic_exposure_0_1": "0-1",
        "green_ratio_0_1": "0-1",
        "water_ratio_0_1": "0-1",
        "precipitation_mm": "mm",
        "feels_like_c": "C",
        "wind_gust_kmh": "km/h",
    }
    return {
        key: {
            "value": value,
            "unit": units.get(key, ""),
            "status": status,
            "provenance": "selftest_fixture",
            "as_of": FIXTURE_TS,
        }
        for key, (value, status) in values.items()
    }


def _fx_route(
    route_id: str,
    name_zh: str,
    mode: str,
    kind: str,
    band: int,
    band_label_zh: str,
    distance_m: float,
    start: list[float],
    end: list[float],
    area: str,
    area_name_zh: str,
    park_relation: dict[str, Any] | None,
    nearby_services: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    speeds = {"walk": 4.8, "run": 9.0, "bike": 18.0}
    return {
        "route_id": route_id,
        "name_zh": name_zh,
        "mode": mode,
        "mode_label": {"walk": "步行", "run": "跑步", "bike": "骑行"}[mode],
        "kind": kind,
        "kind_label": "闭环路线" if kind == "strict_loop" else "单程路线",
        "band": band,
        "band_label": "fixture",
        "band_label_zh": band_label_zh,
        "actual_distance_m": distance_m,
        "distance_m": distance_m,
        "target_distance_m": distance_m,
        "distance_error": metrics.get("distance_error", 0.02),
        "duration_min": round(distance_m / 1000.0 / speeds[mode] * 60.0, 1),
        "speed_kmh": speeds[mode],
        "area": area,
        "area_name_zh": area_name_zh,
        "popular_area_ids": [area],
        "status": "accepted",
        "crs": "CRS84/WGS84 (lon,lat)",
        "coordinate_count": 24,
        "start": start,
        "end": end,
        "bbox": [start[0] - 0.01, start[1] - 0.01, start[0] + 0.01, start[1] + 0.01],
        "road_snapping_ratio": metrics.get("road_snapping_ratio", 0.97),
        "in_district_ratio": metrics.get("in_district_ratio", 1.0),
        "endpoint_offset_m": metrics.get("endpoint_offset_m", 10.0),
        "circuity": metrics.get("circuity", 1.15),
        "repeated_edge_count": metrics.get("repeated_edge_count", 0),
        "proper_self_intersection_count": metrics.get("proper_self_intersection_count", 0),
        "local_uturn_count": metrics.get("local_uturn_count", 0),
        "local_return_loop_count": metrics.get("local_return_loop_count", 0),
        "park_relation": park_relation,
        "nearby_services": nearby_services,
        "edge_count": 30,
        "long_distance": False,
    }


def _fx_risk(fields: dict[str, str], overall: str) -> dict[str, Any]:
    return {"risk": fields, "overall_risk": overall}


def build_fixture() -> tuple[dict[str, Any], dict[str, Any], list[Any], dict[str, Any]]:
    """Minimal in-memory catalog (4 routes) plus dashboard (2 cells); never written to disk."""
    park_relation = {
        "poi_id": 9003,
        "name_zh": "康健园",
        "coord": [121.4280, 31.1770],
        "distance_m": 60.0,
        "relation": "along_route",
        "label": "公园入口",
        "provenance": PROVENANCE,
    }
    routes = [
        _fx_route(
            "FIX_WALK_0001", "fixture滨江步道小环线", "walk", "strict_loop", 0, "轻松短程",
            1820.0, [121.4400, 31.1900], [121.4400, 31.1900], "west_bund", "徐汇滨江与西岸",
            park_relation, [], {"local_uturn_count": 1, "endpoint_offset_m": 8.0, "distance_error": 0.02},
        ),
        _fx_route(
            "FIX_WALK_0002", "fixture徐家汇单程线", "walk", "one_way", 1, "中等距离",
            2900.0, [121.4500, 31.1840], [121.4600, 31.1900], "xujiahui", "徐家汇",
            None,
            [{"poi_id": 9101, "label": "便利店", "distance_m": 80.0}],
            {"repeated_edge_count": 1, "circuity": 1.35, "distance_error": 0.05, "road_snapping_ratio": 0.95},
        ),
        _fx_route(
            "FIX_RUN_0001", "fixture植物园跑圈", "run", "strict_loop", 1, "中距离跑",
            6400.0, [121.4450, 31.1800], [121.4450, 31.1800], "shanghai_botanical_garden", "上海植物园",
            None, [], {"proper_self_intersection_count": 1, "local_uturn_count": 2, "endpoint_offset_m": 12.0},
        ),
        _fx_route(
            "FIX_BIKE_0001", "fixture漕河泾骑行环线", "bike", "strict_loop", 1, "中距骑行",
            12500.0, [121.4350, 31.1700], [121.4350, 31.1700], "caohejing", "漕河泾",
            None, [], {"repeated_edge_count": 2, "local_return_loop_count": 1, "endpoint_offset_m": 15.0},
        ),
    ]
    catalog = {
        "version": 2,
        "generated_at": FIXTURE_TS,
        "run_id": "selftest-fixture",
        "crs": "CRS84/WGS84 (lon,lat)",
        "route_count": len(routes),
        "distance_bands_km": {
            "walk": [[0.5, 2.0], [2.0, 3.5], [3.5, 5.0]],
            "run": [[1.0, 5.0], [5.0, 10.0], [10.0, 15.0]],
            "bike": [[5.0, 10.0], [10.0, 20.0], [20.0, 30.0]],
        },
        "routes": routes,
    }

    def dash_route(route_id: str, mode: str, exposure: dict[str, Any], risk: dict[str, Any], missing: list[str]) -> dict[str, Any]:
        return {
            "route_id": route_id,
            "mode": mode,
            "cell_ids": ["ENV_001"],
            "cell_count": 1,
            "exposure": exposure,
            **risk,
            "missing_fields": missing,
            "data_generated_at": FIXTURE_TS,
        }

    normal_fields = {
        "precipitation_mm": "normal",
        "feels_like_c": "normal",
        "wind_gust_kmh": "normal",
        "aqi_us": "normal",
        "pm25_ug_m3": "normal",
    }
    dashboard = {
        "version": 1,
        "generated_at": FIXTURE_TS,
        "data_generated_at": FIXTURE_TS,
        "run_id": "selftest-fixture",
        "crs": "CRS84/WGS84 (lon,lat)",
        "grid": {"rows": 1, "cols": 2, "cell_count": 2},
        "field_specs": [
            {"key": key, "unit": "", "status_domain": ["measured", "derived", "estimated", "unavailable"], "provenance": "selftest_fixture", "missing_value": None, "description_zh": key}
            for key in ("pm25_ug_m3", "aqi_us", "noise_proxy_db", "traffic_exposure_0_1", "green_ratio_0_1", "water_ratio_0_1", "precipitation_mm", "feels_like_c", "wind_gust_kmh")
        ],
        "risk_thresholds": {
            "precipitation_mm": {"pause": 2.5, "stop": 10.0},
            "feels_like_c": {"pause": 35.0, "stop": 40.0},
            "wind_gust_kmh": {"pause": 40.0, "stop": 62.0},
            "aqi_us": {"caution": 100, "pause": 150, "stop": 200},
            "pm25_ug_m3": {"caution": 75.0, "pause": 115.0, "stop": 150.0},
        },
        "cells": [
            {
                "cell_id": "ENV_001", "row": 0, "col": 0,
                "bbox": [121.40, 31.15, 121.45, 31.20], "center": [121.425, 31.175],
                "inside_district": True,
                "values": _fx_exposure({
                    "precipitation_mm": (0.2, "measured"),
                    "feels_like_c": (30.0, "measured"),
                    "wind_gust_kmh": (18.0, "measured"),
                    "aqi_us": (62.0, "measured"),
                    "pm25_ug_m3": (28.0, "measured"),
                }),
                "missing_fields": [],
            },
            {
                "cell_id": "ENV_002", "row": 0, "col": 1,
                "bbox": [121.45, 31.15, 121.50, 31.20], "center": [121.475, 31.175],
                "inside_district": True,
                "values": _fx_exposure({
                    "precipitation_mm": (1.0, "measured"),
                    "feels_like_c": (31.0, "measured"),
                    "wind_gust_kmh": (22.0, "measured"),
                    "aqi_us": (70.0, "derived"),
                    "pm25_ug_m3": (32.0, "derived"),
                }),
                "missing_fields": [],
            },
        ],
        "routes": [
            dash_route(
                "FIX_WALK_0001", "walk",
                _fx_exposure({
                    "pm25_ug_m3": (28.0, "measured"), "aqi_us": (62.0, "measured"),
                    "noise_proxy_db": (55.0, "derived"), "traffic_exposure_0_1": (0.20, "derived"),
                    "green_ratio_0_1": (0.25, "derived"), "water_ratio_0_1": (0.02, "derived"),
                    "precipitation_mm": (0.2, "measured"), "feels_like_c": (30.5, "measured"),
                    "wind_gust_kmh": (18.0, "measured"),
                }),
                _fx_risk(dict(normal_fields), "normal"), [],
            ),
            dash_route(
                "FIX_WALK_0002", "walk",
                _fx_exposure({
                    "pm25_ug_m3": (None, "unavailable"), "aqi_us": (70.0, "derived"),
                    "noise_proxy_db": (66.0, "derived"), "traffic_exposure_0_1": (0.35, "derived"),
                    "green_ratio_0_1": (0.10, "derived"), "water_ratio_0_1": (0.00, "derived"),
                }),
                _fx_risk(dict(normal_fields), "normal"), ["pm25_ug_m3"],
            ),
            dash_route(
                "FIX_RUN_0001", "run",
                _fx_exposure({
                    "pm25_ug_m3": (45.0, "estimated"), "aqi_us": (95.0, "estimated"),
                    "noise_proxy_db": (58.0, "estimated"), "traffic_exposure_0_1": (0.15, "estimated"),
                    "green_ratio_0_1": (0.42, "estimated"), "water_ratio_0_1": (0.08, "estimated"),
                }),
                _fx_risk({**normal_fields, "aqi_us": "caution"}, "caution"), [],
            ),
            dash_route(
                "FIX_BIKE_0001", "bike",
                _fx_exposure({
                    "pm25_ug_m3": (38.0, "measured"), "aqi_us": (88.0, "measured"),
                    "noise_proxy_db": (70.0, "derived"), "traffic_exposure_0_1": (0.55, "derived"),
                    "green_ratio_0_1": (0.12, "derived"), "water_ratio_0_1": (0.01, "derived"),
                }),
                _fx_risk(dict(normal_fields), "normal"), [],
            ),
        ],
        "missing_rate": {},
        "excluded_fields": [],
    }
    pois = {
        "version": 1,
        "generated_at": FIXTURE_TS,
        "crs": "CRS84/WGS84 (lon,lat)",
        "entries": [
            {"poi_id": 9001, "name_zh": "徐家汇站", "coord": [121.4365, 31.1949], "kind": "station", "category": "transit_entry"},
            {"poi_id": 9002, "name_zh": "云锦路站", "coord": [121.4512, 31.1828], "kind": "subway_entrance", "category": "transit_entry"},
        ],
        "parks": [
            {"poi_id": 9003, "name_zh": "康健园", "coord": [121.4280, 31.1770], "kind": "park", "category": "park"},
        ],
        "services": [],
        "count": 3,
    }
    access = [
        {
            "case_id": "ACC_001",
            "origin": {"poi_id": 9001, "name_zh": "徐家汇站", "kind": "station", "coord": [121.4365, 31.1949]},
            "destination": {"route_id": "FIX_WALK_0002", "route_name": "fixture徐家汇单程线", "mode": "walk", "coord": [121.4500, 31.1840]},
            "estimated_access_min": 17.5,
            "provenance": "selftest_fixture",
            "crs": "CRS84/WGS84 (lon,lat)",
        }
    ]
    return catalog, dashboard, access, pois


def _http_json(url: str, payload: Any | None = None, method: str | None = None, raw: bytes | None = None) -> tuple[int, Any, Any]:
    data = raw if raw is not None else (json.dumps(payload).encode("utf-8") if payload is not None else None)
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            headers = dict(response.headers)
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        headers = dict(exc.headers) if exc.headers else {}
        status = exc.code
    try:
        parsed = json.loads(body.decode("utf-8")) if body else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = None
    return status, parsed, headers


def run_selftest() -> int:
    """Exercise the whole package against an in-memory fixture; returns the failure count."""
    catalog, dashboard, access, pois = build_fixture()
    weights, sha = load_weights()
    results: list[tuple[str, bool, str]] = []

    def record(name: str, check: Callable[[], tuple[bool, str]]) -> None:
        try:
            ok, detail = check()
        except Exception as exc:
            logger.exception("selftest %s crashed", name)
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((name, bool(ok), str(detail)))

    def check_weights() -> tuple[bool, str]:
        ok = (
            set(weights) == set(DIMENSIONS)
            and abs(sum(weights.values()) - 1.0) < 1e-6
            and len(sha) == 64
            and all(char in "0123456789abcdef" for char in sha)
        )
        return ok, f"sum={sum(weights.values()):.6f} sha={sha[:16]}..."

    base_request = {
        "sport": "walk",
        "distance_band": "轻松短程",
        "origin_name": "徐家汇站",
        "preferences": ["riverside", "quiet"],
        "limit": 5,
    }

    def check_recommend_basic() -> tuple[bool, str]:
        response = recommend(base_request, catalog, dashboard, access, pois, weights)
        ok = (
            response["candidate_count"] >= 1
            and response["strategy"] == "model"
            and response["offline"] is True
            and response["weights_sha256"] == sha
            and response["empty_reason"] is None
            and response["primary"] is not None
            and response["primary"]["route_id"] == "FIX_WALK_0001"
            and len(response["alternatives"]) <= 2
            and all(item["mode"] == "walk" for item in response["candidates"])
        )
        return ok, f"candidates={response['candidate_count']} primary={response['primary']['route_id'] if response['primary'] else None}"

    def check_hard_filter() -> tuple[bool, str]:
        response = recommend({"sport": "run"}, catalog, dashboard, access, pois, weights)
        ids = [item["route_id"] for item in response["candidates"]]
        return ids == ["FIX_RUN_0001"], f"run candidates={ids}"

    def check_breakdown_shape() -> tuple[bool, str]:
        response = recommend(base_request, catalog, dashboard, access, pois, weights)
        breakdown = response["primary"]["score_breakdown"]
        ok_keys = set(breakdown) == set(DIMENSIONS)
        effective_sum = sum(
            dim["weight_effective"] for dim in breakdown.values() if dim["score"] is not None
        )
        fields_ok = all(
            {"score", "weight", "weight_effective", "status", "contributors", "reason_zh"} <= set(dim)
            for dim in breakdown.values()
        )
        total = response["primary"]["total_score"]
        ok = ok_keys and fields_ok and abs(effective_sum - 1.0) < 1e-6 and total is not None and 0.0 <= total <= 100.0
        return ok, f"effective_sum={effective_sum:.6f} total={total}"

    def check_env_renormalisation() -> tuple[bool, str]:
        response = recommend(
            {"sport": "walk", "distance_band": "中等距离"}, catalog, dashboard, access, pois, weights
        )
        primary = response["primary"]
        env = primary["score_breakdown"]["environment_health"]
        indicators = [item["indicator"] for item in env["contributors"]]
        ok = (
            primary["route_id"] == "FIX_WALK_0002"
            and env["status"] == "partial"
            and "pm25_ug_m3" not in indicators
            and env["score"] is not None
            and "pm25_ug_m3" in env["missing_indicators"]
        )
        return ok, f"status={env['status']} indicators={indicators}"

    def check_no_origin() -> tuple[bool, str]:
        response = recommend({"sport": "walk"}, catalog, dashboard, access, pois, weights)
        access_dim = response["primary"]["score_breakdown"]["access_convenience"]
        effective_sum = sum(
            dim["weight_effective"]
            for dim in response["primary"]["score_breakdown"].values()
            if dim["score"] is not None
        )
        ok = (
            access_dim["score"] is None
            and access_dim["status"] == "unavailable"
            and response["primary"]["total_score"] is not None
            and abs(effective_sum - 1.0) < 1e-6
        )
        return ok, f"access={access_dim['status']} effective_sum={effective_sum:.6f}"

    def check_kwargs_tolerance() -> tuple[bool, str]:
        request = {**base_request, "future_key": 1}
        response = recommend(request, catalog, dashboard, access, pois, weights, offline=True, bogus_kw="x")
        ignored = response["ignored_request_keys"]
        ok = "bogus_kw" in ignored and "future_key" in ignored and response["offline"] is True
        return ok, f"ignored={ignored}"

    def check_empty_result() -> tuple[bool, str]:
        response = recommend(
            {"sport": "walk", "distance_band": "长距健行"}, catalog, dashboard, access, pois, weights
        )
        ok = (
            response["candidate_count"] == 0
            and response["candidates"] == []
            and response["primary"] is None
            and isinstance(response["empty_reason"], str)
            and bool(response["empty_reason"])
        )
        return ok, f"empty_reason={response['empty_reason'][:40]}..."

    def check_invalid_sport() -> tuple[bool, str]:
        try:
            recommend({"sport": "swim"}, catalog, dashboard, access, pois, weights)
        except InvalidRequestError as exc:
            return True, f"raised InvalidRequestError: {str(exc)[:40]}..."
        return False, "no error raised for sport=swim"

    range_request = {"sport": "walk", "distance_band": (1.5, 3.0), "origin": [121.4365, 31.1949]}

    def check_shortest_access() -> tuple[bool, str]:
        response = shortest_access(range_request, catalog, dashboard, access, pois, weights)
        minutes = [item["estimated_access_min"] for item in response["candidates"]]
        ok = (
            response["strategy"] == "shortest_access"
            and response["candidate_count"] == 2
            and minutes == sorted(minutes)
            and minutes[0] is not None
        )
        return ok, f"minutes={minutes}"

    def check_distance_only() -> tuple[bool, str]:
        response = distance_only(range_request, catalog, dashboard, access, pois, weights)
        ok = (
            response["strategy"] == "distance_only"
            and response["primary"] is not None
            and response["primary"]["route_id"] == "FIX_WALK_0001"
        )
        return ok, f"primary={response['primary']['route_id'] if response['primary'] else None} target=2250m"

    def check_case_list() -> tuple[bool, str]:
        cases = build_case_requests(catalog, pois)
        ok = len(cases) == 81 and cases[0]["case_id"] == "CASE_W_1_P1_O1" and cases[-1]["case_id"] == "CASE_B_3_P3_O3"
        return ok, f"cases={len(cases)} first={cases[0]['case_id']} last={cases[-1]['case_id']}"

    def check_matrix_small() -> tuple[bool, str]:
        cases = build_case_requests(catalog, pois)
        picked = [case for case in cases if case["case_id"] in ("CASE_W_1_P1_O1", "CASE_R_2_P2_O2", "CASE_B_2_P3_O3")]
        scored = [score_case(case, catalog, dashboard, access, pois, weights, write_dir=None) for case in picked]
        matrix = evaluate_matrix(scored)
        required = {
            "case_count", "ready_count", "no_candidate_count", "detour_pass_rate",
            "environment_win_rate", "preference_win_rate", "constraint_pass_rate",
            "mean_detour_ratio", "fatal_data_errors", "support_status",
        }
        ok = (
            required <= set(matrix)
            and matrix["case_count"] == 3
            and matrix["support_status"] in ("supported", "partially_supported", "inconclusive")
        )
        return ok, f"case_count={matrix['case_count']} support={matrix['support_status']} ready={matrix['ready_count']}"

    def check_case_files() -> tuple[bool, str]:
        cases = build_case_requests(catalog, pois)
        case = cases[0]
        temp_dir = Path(tempfile.mkdtemp(prefix="evaluation-selftest-"))
        try:
            score_case(case, catalog, dashboard, access, pois, weights, write_dir=temp_dir)
            names = sorted(item.name for item in temp_dir.iterdir())
            expected = [f"{case['case_id']}__{variant}.json" for variant in ("distance_only", "model", "shortest_access")]
            ok = names == sorted(expected)
            payload = json.loads((temp_dir / f"{case['case_id']}__model.json").read_text(encoding="utf-8"))
            ok = ok and {"profile", "risk", "candidates"} <= set(payload)
            return ok, f"files={names}"
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def check_determinism() -> tuple[bool, str]:
        first = json.dumps(recommend(base_request, catalog, dashboard, access, pois, weights), ensure_ascii=False, sort_keys=True)
        second = json.dumps(recommend(base_request, catalog, dashboard, access, pois, weights), ensure_ascii=False, sort_keys=True)
        return first == second, f"bytes={len(first)}"

    def check_reasons_numeric() -> tuple[bool, str]:
        response = recommend(base_request, catalog, dashboard, access, pois, weights)
        primary = response["primary"]
        reason = primary["recommendation_reason_zh"]
        breakdown = primary["score_breakdown"]
        ok = (
            any(char.isdigit() for char in reason)
            and all(any(char.isdigit() for char in dim["reason_zh"]) or dim["score"] is None for dim in breakdown.values())
            and all(dim["reason_zh"] for dim in breakdown.values())
        )
        return ok, f"reason={reason[:48]}..."

    def check_reliability() -> tuple[bool, str]:
        response = recommend(base_request, catalog, dashboard, access, pois, weights)
        reliability = response["primary"]["data_reliability"]
        #: fixture route 1: 4 derived fields (0.9) and 5 measured fields (1.0)
        expected = round(0.9**4, 6)
        ok = reliability == expected
        return ok, f"reliability={reliability} expected={expected}"

    def check_risk_flags() -> tuple[bool, str]:
        response = recommend({"sport": "run"}, catalog, dashboard, access, pois, weights)
        primary = response["primary"]
        ok = primary["overall_risk"] == "caution" and primary["risk_pause"] is False
        return ok, f"risk={primary['overall_risk']} pause={primary['risk_pause']}"

    def check_api() -> tuple[bool, str]:
        context = api.EvaluationContext(catalog, dashboard, access, pois, weights, sha, [], metrics_write_dir=None)
        server = api.EvaluationHTTPServer(("127.0.0.1", 0), context)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        details: list[str] = []
        ok = False
        try:
            status, health, headers = _http_json(f"{base}/health")
            details.append(f"health={status}")
            ok = (
                status == 200
                and health["status"] == "ok"
                and health["offline"] is True
                and health["route_count"] == 4
                and health["cell_count"] == 2
                and headers.get("Access-Control-Allow-Origin") == "*"
            )
            status, body, _ = _http_json(f"{base}/recommend", payload=base_request)
            details.append(f"recommend={status}")
            ok = ok and status == 200 and body["candidate_count"] >= 1
            status, body, _ = _http_json(f"{base}/recommend", payload={"sport": "swim"})
            details.append(f"invalid_sport={status}")
            ok = ok and status == 400 and body["error"] == "invalid_request"
            status, body, _ = _http_json(f"{base}/recommend", raw=b"{not json")
            details.append(f"malformed={status}")
            ok = ok and status == 400 and body["error"] == "invalid_request"
            status, _, headers = _http_json(f"{base}/health", method="OPTIONS")
            details.append(f"options={status}")
            ok = ok and status == 204 and headers.get("Access-Control-Allow-Origin") == "*"
            status, body, _ = _http_json(f"{base}/routes")
            details.append(f"routes={status}")
            ok = ok and status == 200 and body["route_count"] == 4
            status, body, _ = _http_json(f"{base}/metrics")
            details.append(f"metrics={status}")
            ok = ok and status == 200 and "support_status" in body and body["case_count"] == 81
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        return ok, ", ".join(details)

    record("A01_weights_valid", check_weights)
    record("A02_recommend_basic", check_recommend_basic)
    record("A03_mode_hard_filter", check_hard_filter)
    record("A04_breakdown_shape", check_breakdown_shape)
    record("A05_env_missing_renormalised", check_env_renormalisation)
    record("A06_no_origin_unavailable", check_no_origin)
    record("A07_unknown_kwargs_absorbed", check_kwargs_tolerance)
    record("A08_empty_result_no_raise", check_empty_result)
    record("A09_invalid_sport_raises", check_invalid_sport)
    record("A10_shortest_access_order", check_shortest_access)
    record("A11_distance_only_order", check_distance_only)
    record("A12_case_list_81", check_case_list)
    record("A13_matrix_small", check_matrix_small)
    record("A14_case_files_written", check_case_files)
    record("A15_determinism", check_determinism)
    record("A16_reasons_from_numbers", check_reasons_numeric)
    record("A17_data_reliability_product", check_reliability)
    record("A18_risk_flags", check_risk_flags)
    record("A19_api_endpoints", check_api)

    failures = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failures += 1
    print(f"selftest: {len(results) - failures}/{len(results)} passed")
    return failures


def command_score() -> int:
    """Score the real catalog when present; never fabricate one when absent."""
    inputs = load_default_inputs()
    if inputs["catalog"] is None:
        print("route_catalog.json 尚不存在：路线目录还没生成，跳过评分（不伪造数据）。")
        return 2
    weights, sha = load_weights()
    print(f"weights_sha256={sha}")
    if inputs["dashboard"] is None:
        print("警告：environment_dashboard.json 缺失，环境维度按 unavailable 处理。")
    unique: set[str] = set()
    for sport in SPORTS:
        labels, _ = _band_tables(inputs["catalog"], sport)
        for label in labels:
            request = {"sport": sport, "distance_band": label, "limit": 10}
            response = recommend(
                request, inputs["catalog"], inputs["dashboard"], inputs["access"], inputs["pois"], weights
            )
            primary = response["primary"]
            primary_id = primary["route_id"] if isinstance(primary, dict) else None
            unique.update(item["route_id"] for item in response["candidates"])
            print(
                f"{sport} {label}: candidates={response['candidate_count']} primary={primary_id} partial_data={response['partial_data']}"
            )
    summary = scored_catalog_summary(inputs["catalog"], inputs["dashboard"], weights)
    scored = sum(1 for item in summary["routes"] if item["environment_health"] is not None)
    print(f"catalog routes={summary['route_count']} env_scored={scored} quality_scored={sum(1 for item in summary['routes'] if item['route_quality'] is not None)}")
    return 0


def command_metrics() -> int:
    """Run the 81-case matrix and write per-case artifacts."""
    matrix = run_matrix()
    compact = {key: value for key, value in matrix.items() if key != "per_case"}
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="python -m evaluation", description=__doc__)
    parser.add_argument("--serve", action="store_true", help="run the local HTTP API")
    parser.add_argument("--port", type=int, default=8731, help="API port (default 8731)")
    parser.add_argument("--score", action="store_true", help="score the real route catalog")
    parser.add_argument("--metrics", action="store_true", help="run the 81-case evaluation matrix")
    parser.add_argument("--selftest", action="store_true", help="run the in-memory selftest")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if args.selftest:
        return 1 if run_selftest() else 0
    if args.score:
        return command_score()
    if args.metrics:
        return command_metrics()
    if args.serve:
        api.serve(args.port)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
