import importlib.util
from pathlib import Path


def _load_tool():
    tool_path = Path(__file__).resolve().parents[1] / "tools/build_run_baseline.py"
    spec = importlib.util.spec_from_file_location("build_run_baseline", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_distance_band_boundaries_follow_portfolio_contract() -> None:
    tool = _load_tool()

    assert tool.distance_band(1_000) == "short"
    assert tool.distance_band(4_999) == "short"
    assert tool.distance_band(5_000) == "medium"
    assert tool.distance_band(9_999) == "medium"
    assert tool.distance_band(10_000) == "long"
    assert tool.distance_band(15_000) == "long"
    assert tool.distance_band(15_001) == "out_of_range"


def test_baseline_record_keeps_gate_visual_and_coordinate_truth_separate() -> None:
    tool = _load_tool()
    route = {
        "route_id": "XH_RUN_0033",
        "route_mode": "run",
        "route_name": "测试跑步环线",
        "region_zone": "徐汇滨江",
        "popular_area_ids": ["west_bund"],
        "actual_distance_m": 7_000,
        "target_distance_m": 6_500,
        "route_shape": "strict_loop",
        "validation_status": "needs_review",
        "ordered_nodes": [
            {"node_name": "真实路口", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
            {"node_name": "真实路口", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
        ],
        "polyline_gcj02": [
            {"lng_gcj02": 121.4, "lat_gcj02": 31.1},
            {"lng_gcj02": 121.41, "lat_gcj02": 31.11},
            {"lng_gcj02": 121.4, "lat_gcj02": 31.1},
        ],
        "nearby_pois": [],
        "preference_hits": [],
        "raw_response_paths": ["data/raw/amap/test.json"],
    }
    gate = {
        "status": "fail",
        "failures": [{"code": "false_loop_topology", "message": "假闭环"}],
    }

    record = tool.build_record(route, gate, "needs_review")

    assert record["distance_band"] == "medium"
    assert record["gate_status"] == "fail"
    assert record["gate_failure_codes"] == ["false_loop_topology"]
    assert record["visual_audit_status"] == "pending"
    assert record["geometry_coordinate_system"] == "GCJ-02"
    assert record["poi_audit"]["verified_count"] == 0
    assert len(record["geometry_sha256"]) == 64
