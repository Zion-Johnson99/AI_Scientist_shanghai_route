import importlib.util
from copy import deepcopy
from pathlib import Path


def _load_tool():
    tool_path = Path(__file__).resolve().parents[1] / "tools/sync_bike_waypoints.py"
    spec = importlib.util.spec_from_file_location("sync_bike_waypoints", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _loop_route(index: int) -> dict:
    return {
        "route_id": f"XH_BIKE_{index:04d}",
        "route_mode": "bike",
        "route_name": "测试骑行环线",
        "route_shape": "strict_loop",
        "actual_distance_m": 8000,
        "start_location": {"name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
        "end_location": {"name": "起点", "lng_gcj02": 121.40001, "lat_gcj02": 31.10001},
        "ordered_nodes": [
            {"node_name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
            {"node_name": "转角", "lng_gcj02": 121.41, "lat_gcj02": 31.11},
            {"node_name": "起点", "lng_gcj02": 121.40001, "lat_gcj02": 31.10001},
        ],
    }


def test_seed_sync_closes_bike_loop_at_exact_start_coordinate() -> None:
    tool = _load_tool()
    routes = [_loop_route(index) for index in range(61, 91)]
    seeds = [
        {"route_id": route["route_id"], "route_mode": "bike"}
        for route in routes
    ]

    tool._sync_seed_nodes(routes, seeds)

    assert seeds[0]["end_location"] == seeds[0]["start_location"]
    assert seeds[0]["ordered_nodes"][-1] == seeds[0]["ordered_nodes"][0]


def test_metadata_only_route_0068_uses_accepted_distance() -> None:
    tool = _load_tool()
    candidates = [
        {
            "route_id": "XH_BIKE_0068",
            "route_mode": "bike",
            "target_distance_m": 6200,
            "actual_distance_m": 5811,
            "distance_error_m": 389,
        }
    ]

    tool._sync_metadata_only_targets(deepcopy(candidates))
    tool._sync_metadata_only_targets(candidates)

    assert candidates[0]["target_distance_m"] == 5811
    assert candidates[0]["distance_error_m"] == 0
