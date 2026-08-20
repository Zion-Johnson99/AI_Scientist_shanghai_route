import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest


def _load_tool(name: str):
    tool_path = Path(__file__).resolve().parents[1] / f"tools/{name}.py"
    spec = importlib.util.spec_from_file_location(name, tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_rebuild_rejects_batches_above_five() -> None:
    tool = _load_tool("rebuild_run_routes")
    route_ids = list(tool.ROUTE_SPECS)[:6]

    with pytest.raises(ValueError, match="at most five"):
        tool.select_specs(route_ids)


def test_run_rebuild_refuses_to_write_a_failed_route() -> None:
    tool = _load_tool("rebuild_run_routes")

    with pytest.raises(RuntimeError, match="refusing to write failed routes"):
        tool.apply_routes(
            tool.PROJECT_ROOT,
            {"XH_RUN_0033": {}},
            {"XH_RUN_0033": {"status": "fail"}},
        )


def test_run_rebuild_parses_playwright_raw_result() -> None:
    tool = _load_tool("rebuild_run_routes")

    assert tool._parse_playwright_result('"started"\n') == "started"
    assert (
        tool._parse_playwright_result('"{\\"status\\":\\"done\\"}"\n')
        == '{"status":"done"}'
    )


def test_run_rebuild_invokes_node_entry_without_cmd_escaping() -> None:
    tool = _load_tool("rebuild_run_routes")
    expression = "(() => {\n  return 'started';\n})()"

    command = tool._playwright_command(
        "runroute", expression, Path("playwright-cli.js")
    )

    assert command[0] == "node.exe"
    assert command[1] == "playwright-cli.js"
    assert command[-1] == f"() => ({expression})"


def test_run_rebuild_trims_small_endpoint_hooks() -> None:
    tool = _load_tool("rebuild_run_routes")
    origin = [121.4, 31.1]
    destination = [121.41, 31.11]
    points = [
        [121.40001, 31.10001],
        [121.4001, 31.1001],
        [121.402, 31.102],
        [121.4099, 31.1099],
        [121.40999, 31.10999],
    ]

    trimmed = tool.trim_endpoint_hooks(points, origin, destination, radius_m=30)

    assert trimmed == [origin, [121.402, 31.102], destination]


def test_run_rebuild_retries_transient_playwright_cli_failure() -> None:
    tool = _load_tool("rebuild_run_routes")
    results = iter(
        [
            type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
            type(
                "Result", (), {"returncode": 0, "stdout": '"ready"\n', "stderr": ""}
            )(),
        ]
    )

    value = tool._run_playwright_command(
        ["node.exe"], runner=lambda *args, **kwargs: next(results)
    )

    assert value == "ready"


def test_run_rebuild_browser_requests_have_hard_timeouts() -> None:
    tool = _load_tool("rebuild_run_routes")

    expression = tool.browser_batch_expression(
        {"XH_RUN_0043": tool.ROUTE_SPECS["XH_RUN_0043"]}
    )

    assert "geocode timeout" in expression
    assert "walking timeout" in expression


def test_run_rebuild_rejects_route_below_xuhui_boundary_ratio(monkeypatch) -> None:
    tool = _load_tool("rebuild_run_routes")

    class FakeGate:
        @staticmethod
        def audit_route(route, index):
            return {"status": "pass", "failures": []}

        @staticmethod
        def proper_segment_intersections(points, shape):
            return []

        @staticmethod
        def distance_m(first, second):
            return 20

    route = {
        "shape": "one_way",
        "target_range_m": [900, 1_100],
        "nodes": [
            {"name": "起点", "location": [121.4, 31.1]},
            {"name": "终点", "location": [121.41, 31.11]},
        ],
        "segments": [
            {
                "distance": 1_000,
                "duration": 600,
                "roads": ["测试路"],
                "points": [[121.4, 31.1], [121.41, 31.11]],
            }
        ],
    }
    monkeypatch.setattr(tool, "load_quality_gate", lambda project_root: FakeGate())
    monkeypatch.setattr(
        tool,
        "compute_route_inside_ratio_for_points",
        lambda project_root, points: 0.82,
    )

    audit = tool.audit_routes(tool.PROJECT_ROOT, {"XH_RUN_0048": route})

    assert audit["XH_RUN_0048"]["status"] == "fail"
    assert any(
        failure["code"] == "route_outside_xuhui"
        for failure in audit["XH_RUN_0048"]["failures"]
    )


def test_playwright_run_audit_disables_candidate_cache() -> None:
    script_path = Path(__file__).resolve().parents[1] / "tools/playwright_run_audit.js"
    script = script_path.read_text(encoding="utf-8")

    assert 'cache: "no-store"' in script


def test_run_seed_sync_closes_loop_and_rebuilds_truth_fields() -> None:
    tool = _load_tool("sync_run_waypoints")
    route = {
        "route_id": "XH_RUN_0033",
        "route_mode": "run",
        "route_name": "测试跑步单环",
        "route_shape": "strict_loop",
        "actual_distance_m": 7_200,
        "start_location": {"name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
        "end_location": {"name": "起点", "lng_gcj02": 121.40001, "lat_gcj02": 31.10001},
        "ordered_nodes": [
            {"node_name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
            {"node_name": "转角", "lng_gcj02": 121.41, "lat_gcj02": 31.11},
            {"node_name": "起点", "lng_gcj02": 121.40001, "lat_gcj02": 31.10001},
        ],
    }
    candidates = [deepcopy(route) for _ in range(30)]
    for index, item in enumerate(candidates, start=31):
        item["route_id"] = f"XH_RUN_{index:04d}"
    seeds = [
        {
            "route_id": f"XH_RUN_{index:04d}",
            "route_mode": "run",
            "preference_hits": ["coffee"],
        }
        for index in range(31, 61)
    ]

    tool._sync_seed_nodes(candidates, seeds)

    assert seeds[0]["target_distance_m"] == 7_200
    assert seeds[0]["end_location"] == seeds[0]["start_location"]
    assert seeds[0]["ordered_nodes"][-1] == seeds[0]["ordered_nodes"][0]
    assert seeds[0]["preference_hits"] == []


def test_run_metadata_only_target_sync_is_scoped_to_0046() -> None:
    tool = _load_tool("sync_run_waypoints")
    candidates = [
        {
            "route_id": "XH_RUN_0045",
            "route_mode": "run",
            "actual_distance_m": 3439,
            "target_distance_m": 3300,
        },
        {
            "route_id": "XH_RUN_0046",
            "route_mode": "run",
            "actual_distance_m": 3720,
            "target_distance_m": 3100,
        },
    ]

    tool._sync_metadata_only_targets(candidates)

    assert candidates[0]["target_distance_m"] == 3300
    assert candidates[1]["target_distance_m"] == 3720


def test_run_seed_sync_resolves_seed_id_through_research_records() -> None:
    tool = _load_tool("sync_run_waypoints")
    candidates = [
        {
            "route_id": f"XH_RUN_{index:04d}",
            "route_mode": "run",
            "route_name": f"路线{index}",
            "route_shape": "one_way",
            "actual_distance_m": 1000 + index,
            "start_location": {"name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
            "end_location": {"name": "终点", "lng_gcj02": 121.5, "lat_gcj02": 31.2},
            "ordered_nodes": [
                {"node_name": "起点", "lng_gcj02": 121.4, "lat_gcj02": 31.1},
                {"node_name": "终点", "lng_gcj02": 121.5, "lat_gcj02": 31.2},
            ],
        }
        for index in range(31, 61)
    ]
    seeds = [
        {"seed_id": f"seed-{index}", "route_mode": "run"} for index in range(31, 61)
    ]
    research = [
        {"seed_id": f"seed-{index}", "route_id": f"XH_RUN_{index:04d}"}
        for index in range(31, 61)
    ]

    tool._sync_seed_nodes(candidates, seeds, research)

    assert seeds[0]["route_name"] == "路线31"


def test_run_candidate_poi_sync_requires_matching_geometry() -> None:
    tool = _load_tool("sync_run_waypoints")
    candidate = {
        "route_id": "XH_RUN_0031",
        "route_mode": "run",
        "actual_distance_m": 3_000,
        "polyline_gcj02": [{"lng_gcj02": 121.4, "lat_gcj02": 31.1}],
        "nearby_pois": [],
        "amenity_ids": [],
        "preference_hits": [],
        "preference_search_status": {},
    }
    published = deepcopy(candidate)
    published.update(
        {
            "nearby_pois": [{"poi_id": "amap:test", "poi_type": "toilet"}],
            "amenity_ids": ["amap:test"],
            "preference_hits": ["toilet"],
            "preference_search_status": {"toilet": "verified"},
        }
    )

    tool._sync_candidate_pois([candidate], [published])

    assert candidate["preference_hits"] == ["toilet"]
    assert candidate["nearby_pois"] == published["nearby_pois"]

    published["polyline_gcj02"] = [{"lng_gcj02": 121.5, "lat_gcj02": 31.2}]
    with pytest.raises(ValueError, match="geometry mismatch"):
        tool._sync_candidate_pois([candidate], [published])
