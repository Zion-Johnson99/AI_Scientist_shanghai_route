import importlib.util
from copy import deepcopy
from pathlib import Path


def _load_tool():
    tool_path = Path(__file__).resolve().parents[1] / "tools/sync_walk_waypoints.py"
    spec = importlib.util.spec_from_file_location("sync_walk_waypoints", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_waypoint_cleanup_is_idempotent() -> None:
    tool = _load_tool()
    tool.WAYPOINT_REPLACEMENTS = {
        "XH_WALK_0009": tool.WAYPOINT_REPLACEMENTS["XH_WALK_0009"]
    }
    nodes = [
        {"node_name": "起点"},
        {"node_name": "本地实测单环节点01"},
        {"node_name": "本地实测单环节点02"},
        {"node_name": "本地实测单环节点03"},
        {"node_name": "本地实测单环节点04"},
        {"node_name": "本地实测单环节点05"},
        {"node_name": "终点"},
    ]
    routes = [
        {
            "route_id": "XH_WALK_0009",
            "ordered_nodes": deepcopy(nodes),
            "waypoint_names": [node["node_name"] for node in nodes],
        }
    ]

    tool._clean_candidate_nodes(routes)
    first_result = deepcopy(routes)
    tool._clean_candidate_nodes(routes)

    assert routes == first_result


def test_seed_sync_closes_strict_loop_at_exact_start_coordinate() -> None:
    tool = _load_tool()
    route = {
        "route_mode": "walk",
        "route_name": "测试环线",
        "route_shape": "strict_loop",
        "target_distance_m": 1000,
        "actual_distance_m": 1000,
        "start_location": {"name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
        "end_location": {
            "name": "起点",
            "lng_gcj02": 121.400004,
            "lat_gcj02": 31.100004,
        },
        "ordered_nodes": [
            {"node_name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
            {"node_name": "转角", "lng_gcj02": 121.41, "lat_gcj02": 31.11},
            {"node_name": "起点", "lng_gcj02": 121.400004, "lat_gcj02": 31.100004},
        ],
    }
    routes = [deepcopy(route) for _ in range(30)]
    seeds = [{"route_mode": "walk"} for _ in range(30)]

    tool._sync_seed_nodes(routes, seeds)

    assert seeds[0]["end_location"] == seeds[0]["start_location"]
    assert seeds[0]["ordered_nodes"][-1] == seeds[0]["ordered_nodes"][0]
