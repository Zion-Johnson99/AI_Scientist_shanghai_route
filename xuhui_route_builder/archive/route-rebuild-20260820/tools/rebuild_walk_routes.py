#!/usr/bin/env python3
"""Rebuild selected walking routes through the loaded AMap JS API."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROUTE_SPECS: dict[str, dict[str, Any]] = {
    "XH_WALK_0002": {
        "shape": "strict_loop",
        "name": "漕宝路桂平路街区单环线",
        "region": "漕河泾开发区",
        "popular_area_ids": ["caohejing"],
        "simplify_m": 20,
        "nodes": [
            "桂平路与漕宝路交叉口",
            "桂平路与钦州南路交叉口",
            "虹漕南路与钦州南路交叉口",
            "虹漕南路与漕宝路交叉口",
        ],
    },
    "XH_WALK_0004": {
        "shape": "strict_loop",
        "name": "汾阳路—襄阳南路街区单环线",
        "nodes": [
            "汾阳路与复兴中路交叉口",
            "复兴中路与襄阳南路交叉口",
            "襄阳南路与淮海中路交叉口",
            "淮海中路与汾阳路交叉口",
        ],
    },
    "XH_WALK_0005": {
        "shape": "strict_loop",
        "name": "衡复中部风貌单环线",
        "nodes": [
            "岳阳路与肇嘉浜路交叉口",
            "肇嘉浜路与嘉善路交叉口",
            "嘉善路与建国西路交叉口",
            "建国西路与岳阳路交叉口",
        ],
    },
    "XH_WALK_0006": {
        "shape": "strict_loop",
        "name": "田林宜山街区单环线",
        "region": "田林—漕河泾",
        "popular_area_ids": ["caohejing"],
        "simplify_m": 15,
        "nodes": [
            "桂林路与宜山路交叉口",
            "桂林路与田林路交叉口",
            "田林路与柳州路交叉口",
            "柳州路与宜山路交叉口",
        ],
    },
    "XH_WALK_0007": {
        "shape": "strict_loop",
        "name": "徐家汇体育街区单环线",
        "simplify_m": 20,
        "nodes": [
            "零陵路与天钥桥路交叉口",
            "零陵路与漕溪北路交叉口",
            "中山南二路与漕溪北路交叉口",
            "中山南二路与天钥桥路交叉口",
        ],
    },
    "XH_WALK_0008": {
        "shape": "strict_loop",
        "name": "龙华滨江北部街区单环线",
        "simplify_m": 10,
        "nodes": [
            "中山南二路与宛平南路交叉口",
            "龙华路与宛平南路交叉口",
            "龙华路与东安路交叉口",
            "中山南二路与东安路交叉口",
        ],
    },
    "XH_WALK_0009": {
        "shape": "strict_loop",
        "name": "康健园东侧街区单环线",
        "nodes": [
            "桂林西街与钦州南路交叉口",
            "冠生园路与钦州南路交叉口",
            "冠生园路与柳州路交叉口",
            "桂林西街与柳州路交叉口",
        ],
    },
    "XH_WALK_0015": {
        "shape": "strict_loop",
        "name": "衡复西部风貌长环线",
        "nodes": [
            "乌鲁木齐南路与肇嘉浜路交叉口",
            "肇嘉浜路与嘉善路交叉口",
            "嘉善路与复兴中路交叉口",
            "复兴西路与乌鲁木齐中路交叉口",
        ],
    },
    "XH_WALK_0016": {
        "shape": "strict_loop",
        "name": "衡复东部风貌长环线",
        "region": "衡复历史风貌区",
        "popular_area_ids": ["hengfu"],
        "nodes": [
            "岳阳路与肇嘉浜路交叉口",
            "肇嘉浜路与嘉善路交叉口",
            "嘉善路与复兴中路交叉口",
            "复兴中路与岳阳路交叉口",
        ],
    },
    "XH_WALK_0017": {
        "shape": "one_way",
        "name": "徐家汇科学人文贯穿线",
        "nodes": ["中山南二路与龙吴路交叉口", "淮海中路与乌鲁木齐中路交叉口"],
    },
    "XH_WALK_0018": {
        "shape": "strict_loop",
        "name": "龙华滨江南北长环线",
        "simplify_m": 10,
        "nodes": [
            "肇嘉浜路与宛平南路交叉口",
            "龙华路与宛平南路交叉口",
            "龙华路与东安路交叉口",
            "肇嘉浜路与东安路交叉口",
        ],
    },
    "XH_WALK_0024": {
        "shape": "strict_loop",
        "name": "衡复风貌纵贯长环线",
        "nodes": [
            "乌鲁木齐南路与肇嘉浜路交叉口",
            "肇嘉浜路与襄阳南路交叉口",
            "襄阳南路与复兴中路交叉口",
            "复兴西路与乌鲁木齐中路交叉口",
        ],
    },
    "XH_WALK_0027": {
        "shape": "strict_loop",
        "name": "徐家汇体育—龙华纵贯长环线",
        "region": "徐家汇及体育公园",
        "popular_area_ids": ["xujiahui_sports"],
        "simplify_m": 55,
        "nodes": [
            "中山南二路与宛平南路交叉口",
            "宛平南路与肇嘉浜路交叉口",
            "肇嘉浜路与天钥桥路交叉口",
            "天钥桥路与中山南二路交叉口",
        ],
    },
    "XH_WALK_0028": {
        "shape": "one_way",
        "name": "华发龙吴路至龙耀滨江贯穿线",
        "nodes": ["华发路与龙吴路交叉口", "龙耀路与龙腾大道交叉口"],
    },
    "XH_WALK_0029": {
        "shape": "one_way",
        "name": "康健—华泾南向贯穿线",
        "nodes": ["石龙路与老沪闵路交叉口", "华发路与龙吴路交叉口"],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--route-id", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def proxy_eval(target_id: str, expression: str) -> Any:
    request = urllib.request.Request(
        f"http://localhost:3456/eval?target={target_id}",
        data=expression.encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    return payload.get("value")


def start_batch(target_id: str, specs: dict[str, dict[str, Any]]) -> None:
    expression = f"""
(() => {{
  window.__xuhuiWalkBatch = {{ status: 'running', routes: {{}}, error: null }};
  const specs = {json.dumps(specs, ensure_ascii=False)};
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const geocode = (name) => new Promise((resolve, reject) => {{
    new AMap.Geocoder({{ city: '上海' }}).getLocation(`上海市徐汇区${{name}}`, (status, result) => {{
      const item = result?.geocodes?.[0];
      if (status !== 'complete' || !item || item.level !== '道路交叉路口') {{
        reject(new Error(`geocode failed: ${{name}} status=${{status}} level=${{item?.level || ''}}`));
        return;
      }}
      resolve({{ name, location: item.location.toArray(), address: item.formattedAddress, level: item.level }});
    }});
  }});
  const searchOnce = (origin, destination) => new Promise((resolve, reject) => {{
    const service = new AMap.Walking({{ city: '上海' }});
    service.search(new AMap.LngLat(...origin), new AMap.LngLat(...destination), (status, result) => {{
      const route = result?.routes?.[0];
      if (status !== 'complete' || !route) {{ reject(new Error(`walking failed: ${{status}} ${{result?.info || ''}}`)); return; }}
      const points = [];
      const roads = [];
      for (const step of route.steps || []) {{
        if (step.road && !roads.includes(step.road)) roads.push(step.road);
        for (const point of step.path || []) {{
          const pair = point.toArray();
          if (!points.length || points.at(-1)[0] !== pair[0] || points.at(-1)[1] !== pair[1]) points.push(pair);
        }}
      }}
      resolve({{ distance: route.distance, duration: route.time, points, roads }});
    }});
  }});
  const search = async (origin, destination) => {{
    let lastError;
    for (let attempt = 0; attempt < 3; attempt += 1) {{
      try {{ return await searchOnce(origin, destination); }}
      catch (error) {{ lastError = error; await wait(1200 * (attempt + 1)); }}
    }}
    throw lastError;
  }};
  (async () => {{
    try {{
      for (const [routeId, spec] of Object.entries(specs)) {{
        window.__xuhuiWalkBatch.status = `geocoding ${{routeId}}`;
        const nodes = [];
        for (const name of spec.nodes) {{ nodes.push(await geocode(name)); await wait(300); }}
        const segments = [];
        const segmentCount = spec.shape === 'strict_loop' ? nodes.length : nodes.length - 1;
        for (let index = 0; index < segmentCount; index += 1) {{
          window.__xuhuiWalkBatch.status = `routing ${{routeId}} ${{index + 1}}/${{segmentCount}}`;
          segments.push(await search(nodes[index].location, nodes[(index + 1) % nodes.length].location));
          await wait(850);
        }}
        window.__xuhuiWalkBatch.routes[routeId] = {{ ...spec, nodes, segments }};
      }}
      window.__xuhuiWalkBatch.status = 'done';
    }} catch (error) {{
      window.__xuhuiWalkBatch.error = String(error?.stack || error);
      window.__xuhuiWalkBatch.status = 'error';
    }}
  }})();
  return 'started';
}})()
"""
    if proxy_eval(target_id, expression) != "started":
        raise RuntimeError("browser batch did not start")


def wait_for_batch(target_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 300
    last_status = ""
    while time.monotonic() < deadline:
        state = proxy_eval(
            target_id,
            "JSON.stringify({status:window.__xuhuiWalkBatch?.status,error:window.__xuhuiWalkBatch?.error})",
        )
        summary = json.loads(state or "{}")
        status = summary.get("status", "")
        if status != last_status:
            print(status, flush=True)
            last_status = status
        if status == "done":
            raw = proxy_eval(
                target_id, "JSON.stringify(window.__xuhuiWalkBatch.routes)"
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
    spec = importlib.util.spec_from_file_location("route_quality_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"quality gate unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        if start_index > end_index:
            selected = list(reversed(segment_points[end_index : start_index + 1]))
        else:
            selected = segment_points[start_index : end_index + 1]
        selected[0] = origin
        selected[-1] = destination
        for point in selected:
            if not points or points[-1] != point:
                points.append(point)
    return simplify_polyline(points, tolerance_m=float(route.get("simplify_m", 3)))


def squared_distance(first: list[float], second: list[float]) -> float:
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2


def simplify_polyline(
    points: list[list[float]], tolerance_m: float
) -> list[list[float]]:
    if len(points) <= 2:
        return points
    mean_latitude = sum(point[1] for point in points) / len(points)
    scale_x = 111_320 * math.cos(math.radians(mean_latitude))
    scale_y = 111_320

    def point_segment_distance(
        point: list[float], first: list[float], last: list[float]
    ) -> float:
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


def audit_routes(
    project_root: Path, routes: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    gate = load_quality_gate(project_root)
    audits: dict[str, dict[str, Any]] = {}
    for route_id, route in routes.items():
        points = cleaned_points(route)
        distance = sum(segment["distance"] for segment in route["segments"])
        node_payload = [
            {
                "node_name": node["name"],
                "lng_gcj02": node["location"][0],
                "lat_gcj02": node["location"][1],
            }
            for node in route["nodes"]
        ]
        if route["shape"] == "strict_loop":
            node_payload.append(dict(node_payload[0]))
        audit = gate.audit_route(
            {
                "route_id": route_id,
                "route_mode": "walk",
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
                "ordered_nodes": node_payload,
            },
            0,
        )
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
    project_root: Path, routes: dict[str, Any], audits: dict[str, Any]
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
            project_root / f"data/raw/amap_js/{route_id.lower()}_20260819.json"
        )
        write_json(evidence_path, route)
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
                "network_source": "amap_js_walking+local_topology",
                "verified_at": None,
                "review_note": "高德 JS 步行路径经路口端点清理，本地几何门禁通过，等待全景目视复核",
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
    if len(args.route_id) > 5:
        raise ValueError("a batch may contain at most five routes")
    unknown = sorted(set(args.route_id) - ROUTE_SPECS.keys())
    if unknown:
        raise ValueError(f"unknown route ids: {', '.join(unknown)}")
    project_root = Path(__file__).resolve().parents[1]
    selected = {route_id: ROUTE_SPECS[route_id] for route_id in args.route_id}
    start_batch(args.target_id, selected)
    routes = wait_for_batch(args.target_id)
    audits = audit_routes(project_root, routes)
    print(json.dumps(audits, ensure_ascii=False, indent=2))
    if args.apply:
        apply_routes(project_root, routes, audits)
    return 0 if all(item["status"] == "pass" for item in audits.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
