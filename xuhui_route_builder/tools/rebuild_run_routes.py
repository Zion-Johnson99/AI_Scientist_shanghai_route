#!/usr/bin/env python3
"""Rebuild selected running routes through the loaded AMap JS API."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ROUTE_SPECS: dict[str, dict[str, Any]] = {
    "XH_RUN_0033": {
        "shape": "strict_loop",
        "name": "西岸滨水—云锦路单环",
        "region": "徐汇滨江及西岸",
        "popular_area_ids": ["west_bund"],
        "target_range_m": [5400, 6200],
        "simplify_m": 3,
        "nodes": [
            "瑞宁路与云锦路交叉口",
            "瑞宁路与龙腾大道交叉口",
            "龙耀路与龙腾大道交叉口",
            "龙耀路与云锦路交叉口",
        ],
    },
    "XH_RUN_0034": {
        "shape": "strict_loop",
        "name": "龙华—徐家汇南缘内陆单环",
        "region": "龙华及徐家汇南缘",
        "popular_area_ids": ["longhua", "xujiahui"],
        "target_range_m": [7400, 8200],
        "simplify_m": 3,
        "nodes": [
            "龙华路与云锦路交叉口",
            "龙华西路与天钥桥路交叉口",
            "肇嘉浜路与天钥桥路交叉口",
            "肇嘉浜路与宛平南路交叉口",
        ],
    },
    "XH_RUN_0036": {
        "shape": "strict_loop",
        "name": "植物园外围公共道路单环",
        "region": "上海植物园及周边",
        "popular_area_ids": ["shanghai_botanical_garden"],
        "target_range_m": [5500, 7000],
        "nodes": [
            "老沪闵路与百色路交叉口",
            "百色路与龙吴路交叉口",
            "石龙路与龙吴路交叉口",
            "石龙路与老沪闵路交叉口",
        ],
    },
    "XH_RUN_0041": {
        "shape": "strict_loop",
        "name": "植物园北缘公共道路短环",
        "region": "上海植物园及周边",
        "popular_area_ids": ["shanghai_botanical_garden"],
        "target_range_m": [2700, 3500],
        "nodes": [
            "龙川北路与罗城路交叉口",
            "龙川北路与石龙路交叉口",
            "石龙路与东泉路交叉口",
            "东泉路与罗城路交叉口",
        ],
    },
    "XH_RUN_0042": {
        "shape": "strict_loop",
        "name": "徐家汇南侧街区短环",
        "region": "徐家汇南侧",
        "popular_area_ids": ["xujiahui"],
        "target_range_m": [1800, 2200],
        "nodes": [
            "零陵路与宛平南路交叉口",
            "零陵路与天钥桥路交叉口",
            "斜土路与天钥桥路交叉口",
            "斜土路与宛平南路交叉口",
        ],
    },
    "XH_RUN_0043": {
        "shape": "strict_loop",
        "name": "徐家汇凯旋—漕溪北路环",
        "region": "徐家汇西侧及凯旋路",
        "popular_area_ids": ["xujiahui"],
        "target_range_m": [4000, 6500],
        "nodes": [
            "淮海西路与凯旋路交叉口",
            "宜山路与凯旋路交叉口",
            "宜山路与漕溪北路交叉口",
            "虹桥路与漕溪北路交叉口",
        ],
    },
    "XH_RUN_0044": {
        "shape": "strict_loop",
        "name": "衡复西部风貌短环",
        "region": "衡复风貌区及徐家汇",
        "popular_area_ids": ["hengfu", "xujiahui"],
        "target_range_m": [4000, 4800],
        "nodes": [
            "复兴西路与乌鲁木齐中路交叉口",
            "复兴中路与嘉善路交叉口",
            "肇嘉浜路与嘉善路交叉口",
            "肇嘉浜路与乌鲁木齐南路交叉口",
        ],
    },
    "XH_RUN_0047": {
        "shape": "strict_loop",
        "name": "徐家汇体育文化中环",
        "region": "徐家汇",
        "popular_area_ids": ["xujiahui"],
        "target_range_m": [6800, 7300],
        "nodes": [
            "淮海西路与凯旋路交叉口",
            "宜山路与凯旋路交叉口",
            "中山南二路与漕溪北路交叉口",
            "中山南二路与天钥桥路交叉口",
            "肇嘉浜路与天平路交叉口",
            "虹桥路与华山路交叉口",
        ],
    },
    "XH_RUN_0048": {
        "shape": "strict_loop",
        "name": "徐家汇肇嘉浜路—零陵路短环",
        "region": "徐家汇南侧",
        "popular_area_ids": ["hengfu", "xujiahui"],
        "target_range_m": [1800, 3500],
        "nodes": [
            "肇嘉浜路与宛平南路交叉口",
            "肇嘉浜路与天钥桥路交叉口",
            "零陵路与天钥桥路交叉口",
            "零陵路与宛平南路交叉口",
        ],
    },
    "XH_RUN_0051": {
        "shape": "strict_loop",
        "name": "徐家汇—漕河泾东部城市长环",
        "region": "徐家汇—漕河泾东部",
        "popular_area_ids": ["xujiahui", "caohejing", "longhua"],
        "target_range_m": [10000, 15000],
        "simplify_m": 3,
        "endpoint_trim_m": 150,
        "nodes": [
            "肇嘉浜路与天平路交叉口",
            "虹桥路与凯旋路交叉口",
            "宜山路与桂林路交叉口",
            "漕宝路与桂林路交叉口",
            "中山南二路与漕溪北路交叉口",
            "肇嘉浜路与宛平南路交叉口",
        ],
    },
    "XH_RUN_0052": {
        "shape": "strict_loop",
        "name": "植物园—华发南部外围长环",
        "region": "上海植物园—华泾",
        "popular_area_ids": ["shanghai_botanical_garden", "huajing"],
        "target_range_m": [10000, 12000],
        "nodes": [
            "石龙路与老沪闵路交叉口",
            "石龙路与龙吴路交叉口",
            "华发路与龙吴路交叉口",
            "华发路与老沪闵路交叉口",
        ],
    },
    "XH_RUN_0053": {
        "shape": "strict_loop",
        "name": "龙华—植物园北部扩展长环",
        "region": "龙华—上海植物园北部",
        "popular_area_ids": ["longhua", "shanghai_botanical_garden"],
        "target_range_m": [13000, 15000],
        "nodes": [
            "中山南二路与漕溪北路交叉口",
            "龙水南路与龙吴路交叉口",
            "罗秀路与龙吴路交叉口",
            "罗秀路与老沪闵路交叉口",
            "石龙路与老沪闵路交叉口",
        ],
    },
    "XH_RUN_0054": {
        "shape": "one_way",
        "name": "漕河泾—华泾南部单程线",
        "region": "漕河泾—华泾",
        "popular_area_ids": ["caohejing", "kangjian", "huajing"],
        "target_range_m": [10000, 13000],
        "nodes": [
            "虹桥路与凯旋路交叉口",
            "桂林路与宜山路交叉口",
            "华泾路与龙吴路交叉口",
        ],
    },
    "XH_RUN_0055": {
        "shape": "one_way",
        "name": "徐家汇—康健—华泾南向长线",
        "region": "徐家汇—康健—华泾",
        "popular_area_ids": [
            "caohejing",
            "kangjian",
            "shanghai_botanical_garden",
            "huajing",
        ],
        "target_range_m": [10000, 15000],
        "nodes": [
            "淮海西路与凯旋路交叉口",
            "桂林路与钦州南路交叉口",
            "石龙路与老沪闵路交叉口",
            "华发路与龙吴路交叉口",
            "华泾路与龙吴路交叉口",
        ],
    },
    "XH_RUN_0056": {
        "shape": "one_way",
        "name": "衡复—康健—华泾长线",
        "region": "衡复风貌区—康健—华泾",
        "popular_area_ids": ["hengfu", "kangjian", "huajing"],
        "target_range_m": [10000, 14000],
        "simplify_m": 3,
        "nodes": [
            "武康路与湖南路交叉口",
            "桂林路与钦州南路交叉口",
            "石龙路与老沪闵路交叉口",
            "华泾路与龙吴路交叉口",
        ],
    },
    "XH_RUN_0057": {
        "shape": "strict_loop",
        "name": "徐家汇—桂林—龙华城市长环",
        "region": "徐家汇—桂林—龙华",
        "popular_area_ids": ["caohejing", "xujiahui"],
        "target_range_m": [10000, 15000],
        "endpoint_trim_m": 150,
        "nodes": [
            "肇嘉浜路与东安路交叉口",
            "虹桥路与凯旋路交叉口",
            "宜山路与桂林路交叉口",
            "漕宝路与桂林路交叉口",
            "中山南二路与天钥桥路交叉口",
            "中山南二路与东安路交叉口",
        ],
    },
    "XH_RUN_0059": {
        "shape": "strict_loop",
        "name": "龙华—植物园北部长环",
        "region": "龙华—上海植物园北部",
        "popular_area_ids": ["longhua", "shanghai_botanical_garden"],
        "target_range_m": [10000, 13500],
        "nodes": [
            "中山南二路与漕溪北路交叉口",
            "罗秀路与龙吴路交叉口",
            "罗秀路与老沪闵路交叉口",
            "石龙路与老沪闵路交叉口",
        ],
    },
    "XH_RUN_0060": {
        "shape": "one_way",
        "name": "华泾—徐家汇南北长线",
        "region": "华泾—上海植物园—徐家汇",
        "popular_area_ids": [
            "huajing",
            "shanghai_botanical_garden",
            "kangjian",
            "xujiahui",
        ],
        "target_range_m": [10000, 12500],
        "nodes": [
            "华泾路与龙吴路交叉口",
            "复兴中路与乌鲁木齐中路交叉口",
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--route-id", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def select_specs(route_ids: list[str]) -> dict[str, dict[str, Any]]:
    if len(route_ids) > 5:
        raise ValueError("a batch may contain at most five routes")
    unknown = sorted(set(route_ids) - ROUTE_SPECS.keys())
    if unknown:
        raise ValueError(f"unknown route ids: {', '.join(unknown)}")
    return {route_id: ROUTE_SPECS[route_id] for route_id in route_ids}


def _parse_playwright_result(output: str) -> Any:
    return json.loads(output.strip())


def _find_playwright_cli_entry() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    npm_cache = Path(local_app_data) / "npm-cache/_npx"
    matches = list(npm_cache.glob("*/node_modules/@playwright/cli/playwright-cli.js"))
    if not matches:
        raise RuntimeError("cached @playwright/cli entry was not found")
    return max(matches, key=lambda path: path.stat().st_mtime)


def _playwright_command(target_id: str, expression: str, entry: Path) -> list[str]:
    return [
        "node.exe",
        str(entry),
        "--raw",
        f"-s={target_id}",
        "eval",
        f"() => ({expression})",
    ]


def _run_playwright_command(command: list[str], runner=subprocess.run) -> Any:
    for attempt in range(3):
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
        )
        if completed.returncode == 0:
            return _parse_playwright_result(completed.stdout)
        detail = completed.stderr.strip() or completed.stdout.strip()
        if detail:
            raise RuntimeError(f"playwright eval failed: {detail}")
        if attempt < 2:
            time.sleep(0.25)
    raise RuntimeError("playwright eval failed after three empty responses")


def proxy_eval(target_id: str, expression: str) -> Any:
    command = _playwright_command(target_id, expression, _find_playwright_cli_entry())
    return _run_playwright_command(command)


def browser_batch_expression(specs: dict[str, dict[str, Any]]) -> str:
    expression = f"""
(() => {{
  window.__xuhuiRunCache ||= {{ geocodes: {{}}, segments: {{}} }};
  window.__xuhuiRunBatch = {{ status: 'running', routes: {{}}, error: null, apiCalls: 0, cacheHits: 0 }};
  const specs = {json.dumps(specs, ensure_ascii=False)};
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const geocode = (name) => new Promise((resolve, reject) => {{
    const cached = window.__xuhuiRunCache.geocodes[name];
    if (cached) {{ window.__xuhuiRunBatch.cacheHits += 1; resolve(cached); return; }}
    const timeout = setTimeout(() => reject(new Error(`geocode timeout: ${{name}}`)), 15000);
    new AMap.Geocoder({{ city: '上海' }}).getLocation(`上海市徐汇区${{name}}`, (status, result) => {{
      clearTimeout(timeout);
      window.__xuhuiRunBatch.apiCalls += 1;
      const item = result?.geocodes?.[0];
      if (status !== 'complete' || !item) {{ reject(new Error(`geocode failed: ${{name}} status=${{status}} info=${{result?.info || ''}}`)); return; }}
      const value = {{ name, location: item.location.toArray(), address: item.formattedAddress, level: item.level }};
      window.__xuhuiRunCache.geocodes[name] = value;
      resolve(value);
    }});
  }});
  const searchOnce = (origin, destination) => new Promise((resolve, reject) => {{
    const key = `${{origin.join(',')}}>${{destination.join(',')}}`;
    const cached = window.__xuhuiRunCache.segments[key];
    if (cached) {{ window.__xuhuiRunBatch.cacheHits += 1; resolve(cached); return; }}
    const service = new AMap.Walking({{ city: '上海' }});
    const timeout = setTimeout(() => reject(new Error(`walking timeout: ${{key}}`)), 20000);
    service.search(new AMap.LngLat(...origin), new AMap.LngLat(...destination), (status, result) => {{
      clearTimeout(timeout);
      window.__xuhuiRunBatch.apiCalls += 1;
      const route = result?.routes?.[0];
      const info = String(result?.info || '');
      if (status !== 'complete' || !route) {{ reject(new Error(`walking failed: status=${{status}} info=${{info}}`)); return; }}
      const points = [];
      const roads = [];
      for (const step of route.steps || []) {{
        if (step.road && !roads.includes(step.road)) roads.push(step.road);
        for (const point of step.path || []) {{
          const pair = point.toArray();
          if (!points.length || points.at(-1)[0] !== pair[0] || points.at(-1)[1] !== pair[1]) points.push(pair);
        }}
      }}
      const value = {{ distance: route.distance, duration: route.time, points, roads }};
      window.__xuhuiRunCache.segments[key] = value;
      resolve(value);
    }});
  }});
  (async () => {{
    try {{
      for (const [routeId, spec] of Object.entries(specs)) {{
        window.__xuhuiRunBatch.status = `geocoding ${{routeId}}`;
        const nodes = [];
        for (const name of spec.nodes) {{ nodes.push(await geocode(name)); await wait(250); }}
        const segments = [];
        const segmentCount = spec.shape === 'strict_loop' ? nodes.length : nodes.length - 1;
        for (let index = 0; index < segmentCount; index += 1) {{
          window.__xuhuiRunBatch.status = `routing ${{routeId}} ${{index + 1}}/${{segmentCount}}`;
          segments.push(await searchOnce(nodes[index].location, nodes[(index + 1) % nodes.length].location));
          await wait(750);
        }}
        window.__xuhuiRunBatch.routes[routeId] = {{ ...spec, nodes, segments }};
      }}
      window.__xuhuiRunBatch.status = 'done';
    }} catch (error) {{
      window.__xuhuiRunBatch.error = String(error?.stack || error);
      window.__xuhuiRunBatch.status = 'error';
    }}
  }})();
  return 'started';
}})()
"""
    return expression


def start_batch(target_id: str, specs: dict[str, dict[str, Any]]) -> None:
    expression = browser_batch_expression(specs)
    if proxy_eval(target_id, expression) != "started":
        raise RuntimeError("browser batch did not start")


def wait_for_batch(target_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 600
    last_status = ""
    while time.monotonic() < deadline:
        state = proxy_eval(
            target_id,
            "JSON.stringify({status:window.__xuhuiRunBatch?.status,error:window.__xuhuiRunBatch?.error})",
        )
        summary = json.loads(state or "{}")
        status = summary.get("status", "")
        if status != last_status:
            print(status, flush=True)
            last_status = status
        if status == "done":
            raw = proxy_eval(
                target_id,
                "JSON.stringify({routes:window.__xuhuiRunBatch.routes,apiCalls:window.__xuhuiRunBatch.apiCalls,cacheHits:window.__xuhuiRunBatch.cacheHits})",
            )
            return json.loads(raw)
        if status == "error":
            raise RuntimeError(summary.get("error") or "browser batch failed")
        time.sleep(1)
    raise TimeoutError("browser batch timed out")


def load_quality_gate(project_root: Path):
    path = (
        project_root.parent
        / ".agents/skills/optimize-xuhui-routes/scripts/route_quality_gate.py"
    )
    spec = importlib.util.spec_from_file_location("run_route_quality_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"quality gate unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def squared_distance(first: list[float], second: list[float]) -> float:
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2


def point_distance_m(first: list[float], second: list[float]) -> float:
    mean_latitude = math.radians((first[1] + second[1]) / 2)
    dx = (first[0] - second[0]) * 111_320 * math.cos(mean_latitude)
    dy = (first[1] - second[1]) * 111_320
    return math.hypot(dx, dy)


def trim_endpoint_hooks(
    points: list[list[float]],
    origin: list[float],
    destination: list[float],
    radius_m: float,
) -> list[list[float]]:
    middle = [
        point
        for point in points
        if point_distance_m(point, origin) > radius_m
        and point_distance_m(point, destination) > radius_m
    ]
    return [origin, *middle, destination]


def simplify_polyline(
    points: list[list[float]], tolerance_m: float
) -> list[list[float]]:
    if len(points) <= 2:
        return points
    mean_latitude = sum(point[1] for point in points) / len(points)
    scale_x = 111_320 * math.cos(math.radians(mean_latitude))
    scale_y = 111_320

    def point_segment_distance(point, first, last) -> float:
        px, py = point[0] * scale_x, point[1] * scale_y
        ax, ay = first[0] * scale_x, first[1] * scale_y
        bx, by = last[0] * scale_x, last[1] * scale_y
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        fraction = (
            0.0
            if denominator == 0
            else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denominator))
        )
        return math.hypot(px - (ax + fraction * dx), py - (ay + fraction * dy))

    distances = [
        point_segment_distance(points[index], points[0], points[-1])
        for index in range(1, len(points) - 1)
    ]
    maximum = max(distances, default=0.0)
    if maximum <= tolerance_m:
        return [points[0], points[-1]]
    split = distances.index(maximum) + 1
    return simplify_polyline(points[: split + 1], tolerance_m)[:-1] + simplify_polyline(
        points[split:], tolerance_m
    )


def cleaned_points(route: dict[str, Any]) -> list[list[float]]:
    points: list[list[float]] = []
    nodes = route["nodes"]
    for index, segment in enumerate(route["segments"]):
        origin = nodes[index]["location"]
        destination = nodes[(index + 1) % len(nodes)]["location"]
        segment_points = segment["points"]
        start_index = min(
            range(len(segment_points)),
            key=lambda item: squared_distance(segment_points[item], origin),
        )
        end_index = min(
            range(len(segment_points)),
            key=lambda item: squared_distance(segment_points[item], destination),
        )
        selected = (
            list(reversed(segment_points[end_index : start_index + 1]))
            if start_index > end_index
            else segment_points[start_index : end_index + 1]
        )
        selected = trim_endpoint_hooks(
            selected,
            origin,
            destination,
            radius_m=float(route.get("endpoint_trim_m", 40)),
        )
        for point in selected:
            if not points or points[-1] != point:
                points.append(point)
    return simplify_polyline(points, tolerance_m=float(route.get("simplify_m", 3)))


def compute_route_inside_ratio_for_points(
    project_root: Path, points: list[list[float]]
) -> float:
    sys.path.insert(0, str(project_root / "src"))
    from xuhui_route_builder.cli import _load_boundary_polygons
    from xuhui_route_builder.geo import polyline_to_coordinate_pairs
    from xuhui_route_builder.validation import compute_route_inside_ratio

    boundary = _load_boundary_polygons(project_root / "data/web/xuhui_boundary.geojson")
    coordinate_pairs = polyline_to_coordinate_pairs(
        [f"{lng},{lat}" for lng, lat in points]
    )
    return compute_route_inside_ratio(coordinate_pairs, boundary)


def audit_routes(
    project_root: Path, routes: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    gate = load_quality_gate(project_root)
    audits: dict[str, dict[str, Any]] = {}
    for route_id, route in routes.items():
        points = cleaned_points(route)
        distance = sum(segment["distance"] for segment in route["segments"])
        inside_ratio = compute_route_inside_ratio_for_points(project_root, points)
        nodes = [
            {
                "node_name": node["name"],
                "lng_gcj02": node["location"][0],
                "lat_gcj02": node["location"][1],
            }
            for node in route["nodes"]
        ]
        if route["shape"] == "strict_loop":
            nodes.append(dict(nodes[0]))
        audit = gate.audit_route(
            {
                "route_id": route_id,
                "route_mode": "run",
                "route_shape": route["shape"],
                "polyline_gcj02": points,
                "actual_distance_m": distance,
                "target_distance_m": distance,
                "start_location": {
                    "lng_gcj02": points[0][0],
                    "lat_gcj02": points[0][1],
                },
                "end_location": {
                    "lng_gcj02": points[-1][0],
                    "lat_gcj02": points[-1][1],
                },
                "ordered_nodes": nodes,
            },
            0,
        )
        intersection_pairs = gate.proper_segment_intersections(points, route["shape"])
        audit["diagnostics"] = {
            "route_inside_ratio": inside_ratio,
            "self_intersections": [
                {
                    "first_segment": pair[0],
                    "second_segment": pair[1],
                    "first": points[pair[0] : pair[0] + 2],
                    "second": points[pair[1] : pair[1] + 2],
                }
                for pair in intersection_pairs
            ],
            "local_uturns": [
                {"index": index, "points": points[index - 1 : index + 2]}
                for index in range(1, len(points) - 1)
                if gate.distance_m(points[index - 1], points[index]) >= 15
                and gate.distance_m(points[index], points[index + 1]) >= 15
                and gate.distance_m(points[index - 1], points[index + 1]) <= 10
            ],
        }
        minimum, maximum = route["target_range_m"]
        if not minimum <= distance <= maximum:
            audit["failures"].append(
                {
                    "code": "planned_distance_range",
                    "message": f"actual {distance} outside {minimum}-{maximum}",
                }
            )
            audit["status"] = "fail"
        if inside_ratio < 0.9:
            audit["failures"].append(
                {
                    "code": "route_outside_xuhui",
                    "message": f"route inside ratio {inside_ratio:.1%} below 90%",
                }
            )
            audit["status"] = "fail"
        audits[route_id] = audit
    return audits


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def apply_routes(
    project_root: Path,
    routes: dict[str, Any],
    audits: dict[str, Any],
    execution: dict[str, Any] | None = None,
) -> None:
    failed = [
        route_id for route_id, audit in audits.items() if audit["status"] != "pass"
    ]
    if failed:
        raise RuntimeError(f"refusing to write failed routes: {', '.join(failed)}")
    sys.path.insert(0, str(project_root / "src"))
    from xuhui_route_builder.geo import polyline_to_coordinate_pairs

    candidate_path = project_root / "data/interim/pilot_candidates.json"
    candidates = json.loads(candidate_path.read_text(encoding="utf-8"))
    by_id = {route["route_id"]: route for route in candidates}
    for route_id, route in routes.items():
        current = by_id[route_id]
        evidence_path = (
            project_root / f"data/raw/amap_js/{route_id.lower()}_20260820.json"
        )
        evidence = {**route, "execution": execution or {}}
        write_json(evidence_path, evidence)
        points = cleaned_points(route)
        pairs = polyline_to_coordinate_pairs([f"{lng},{lat}" for lng, lat in points])
        distance = int(sum(segment["distance"] for segment in route["segments"]))
        duration = int(sum(segment["duration"] for segment in route["segments"]))
        nodes = [
            {
                "node_name": node["name"],
                "node_type": "road_intersection",
                "source_url": current.get("source_url", ""),
                "poi_id": None,
                "lng_gcj02": node["location"][0],
                "lat_gcj02": node["location"][1],
                "lng_wgs84": None,
                "lat_wgs84": None,
            }
            for node in route["nodes"]
        ]
        if route["shape"] == "strict_loop":
            nodes.append(dict(nodes[0]))
        roads = list(
            dict.fromkeys(
                road for segment in route["segments"] for road in segment["roads"]
            )
        )
        first, last = nodes[0], nodes[-1]
        current.update(
            {
                "route_name": route["name"],
                "route_shape": route["shape"],
                "region_zone": route.get("region", current["region_zone"]),
                "popular_area_ids": route.get(
                    "popular_area_ids", current.get("popular_area_ids", [])
                ),
                "target_distance_m": distance,
                "actual_distance_m": distance,
                "duration_s": duration,
                "start_location": {
                    **current["start_location"],
                    "name": first["node_name"],
                    "lng_gcj02": first["lng_gcj02"],
                    "lat_gcj02": first["lat_gcj02"],
                },
                "end_location": {
                    **current["end_location"],
                    "name": last["node_name"],
                    "lng_gcj02": last["lng_gcj02"],
                    "lat_gcj02": last["lat_gcj02"],
                },
                "ordered_nodes": nodes,
                "polyline_gcj02": [pair.model_dump(mode="json") for pair in pairs],
                "road_names": roads,
                "turn_count": max(
                    0, sum(len(segment["roads"]) for segment in route["segments"]) - 1
                ),
                "distance_error_m": 0,
                "loop_flag": route["shape"] == "strict_loop",
                "source_method": "amap_js_segmented_direction+endpoint_audit",
                "geometry_source": "audited_import",
                "geometry_status": "complete",
                "validation_status": "pending",
                "snap_ratio": None,
                "network_source": "amap_js_walking_20260820+local_topology",
                "source_accessed_at": "2026-08-20",
                "verified_at": None,
                "review_note": "高德 JS 跑步适用步行路径经真实路口生成，本地几何门禁通过，等待全景目视复核",
                "raw_response_paths": [
                    evidence_path.relative_to(project_root).as_posix()
                ],
                "waypoint_names": [node["node_name"] for node in nodes],
                "nearby_pois": [],
                "amenity_ids": [],
                "preference_hits": [],
            }
        )
    write_json(candidate_path, candidates)


def main() -> int:
    args = parse_args()
    selected = select_specs(args.route_id)
    start_batch(args.target_id, selected)
    execution = wait_for_batch(args.target_id)
    routes = execution["routes"]
    audits = audit_routes(PROJECT_ROOT, routes)
    print(
        json.dumps(
            {
                "audits": audits,
                "apiCalls": execution["apiCalls"],
                "cacheHits": execution["cacheHits"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.apply:
        apply_routes(
            PROJECT_ROOT,
            routes,
            audits,
            {"apiCalls": execution["apiCalls"], "cacheHits": execution["cacheHits"]},
        )
    return 0 if all(item["status"] == "pass" for item in audits.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
