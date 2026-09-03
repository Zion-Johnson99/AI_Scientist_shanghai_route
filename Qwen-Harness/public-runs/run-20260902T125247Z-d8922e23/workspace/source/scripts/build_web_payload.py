"""Build the consolidated browser payload, the harness adapter and the local product.

Reads whatever data-contract files already exist under this run, tolerates every
missing input with an explicit ``missing_inputs`` entry, and never fabricates
route geometry. Run from ``workspace/source``::

    env -u DASHSCOPE_API_KEY -u OPENAI_API_KEY python scripts/build_web_payload.py

Outputs:
  * ``workspace/source/web/data/app_payload.json``
  * ``publish/research_harness_latest.json``
  * ``publish/local-product/`` (self-contained static site)
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = SOURCE_ROOT.parents[1]
WEB_DATA_DIR = SOURCE_ROOT / "xuhui_route_builder" / "data" / "web"
EXPERIMENTS_DIR = RUN_ROOT / "experiments"
PUBLISH_DIR = RUN_ROOT / "publish"
LOCAL_PRODUCT_DIR = PUBLISH_DIR / "local-product"
SOURCE_WEB_DIR = SOURCE_ROOT / "web"

CRS = "CRS84/WGS84 (lon,lat)"
MAX_POLYLINE_POINTS = 400

MANDATORY_INPUTS: tuple[str, ...] = (
    "route_catalog.json",
    "xuhui_routes.geojson",
    "xuhui_boundary.geojson",
    "xuhui_entries.geojson",
    "poi_catalog.json",
    "access_cases.json",
    "environment_dashboard.json",
    "default_weights.json",
    "evaluation_package",
)

# Deterministic recommendation grid: 3 modes x 3 bands x 4 preference sets x 3
# origins = 108 profiles. Preference sets and origins are fixed here so the
# profile keys are stable across rebuilds.
MODES: tuple[str, ...] = ("walk", "run", "bike")
BANDS: tuple[str, ...] = ("band1", "band2", "band3")
PREFERENCE_SETS: dict[str, tuple[str, ...]] = {
    "riverside": ("滨江", "水岸"),
    "park": ("公园", "绿荫"),
    "quiet": ("安静",),
    "urban": ("城市风景",),
}
ORIGINS: dict[str, dict[str, Any]] = {
    "xujiahui": {"name_zh": "徐家汇", "coord": [121.4365, 31.1945]},
    "longhua": {"name_zh": "龙华", "coord": [121.4505, 31.1815]},
    "south_station": {"name_zh": "上海南站", "coord": [121.4275, 31.1545]},
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any | None:
    """Return parsed JSON or None; a missing/corrupt input never crashes the build."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] failed to read {path.name}: {exc}", file=sys.stderr)
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def round_coord(coord: Any) -> list[float]:
    lon = round(float(coord[0]), 6)
    lat = round(float(coord[1]), 6)
    return [lon, lat]


def round_coords(coords: list[Any]) -> list[list[float]]:
    return [round_coord(c) for c in coords]


def downsample(coords: list[list[float]], max_points: int = MAX_POLYLINE_POINTS) -> list[list[float]]:
    """Uniform-stride downsample that always keeps the first and last point."""
    n = len(coords)
    if n <= max_points:
        return coords
    stride = math.ceil((n - 1) / (max_points - 1))
    out = coords[::stride]
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out[:max_points]


def build_routes(catalog: dict[str, Any] | None, geojson: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(catalog, dict) or not isinstance(geojson, dict):
        return []
    geom_by_id: dict[str, list[list[float]]] = {}
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        route_id = feature.get("id") or props.get("route_id")
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if isinstance(route_id, str) and isinstance(coords, list):
            geom_by_id[route_id] = downsample(round_coords(coords))

    keep_fields = (
        "route_id", "name_zh", "mode", "mode_label", "kind", "kind_label", "band_label_zh",
        "distance_m", "actual_distance_m", "duration_min", "area", "area_name_zh", "status",
        "start", "end", "bbox", "coordinate_count", "road_snapping_ratio", "in_district_ratio",
        "circuity", "repeated_edge_count", "proper_self_intersection_count",
        "local_uturn_count", "local_return_loop_count", "park_relation", "nearby_services",
        "long_distance", "band",
    )
    routes: list[dict[str, Any]] = []
    for entry in catalog.get("routes", []):
        route_id = entry.get("route_id")
        coords = geom_by_id.get(route_id)
        if coords is None:
            # Never fabricate geometry: a catalog row without a GeoJSON line is skipped.
            print(f"[warn] route {route_id} has no geometry in xuhui_routes.geojson", file=sys.stderr)
            continue
        slim: dict[str, Any] = {field: entry.get(field) for field in keep_fields}
        slim["start"] = round_coord(entry["start"]) if entry.get("start") else coords[0]
        slim["end"] = round_coord(entry["end"]) if entry.get("end") else coords[-1]
        if isinstance(entry.get("bbox"), list):
            slim["bbox"] = [round(float(v), 6) for v in entry["bbox"]]
        else:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            slim["bbox"] = [min(lons), min(lats), max(lons), max(lats)]
        slim["coordinates"] = coords
        routes.append(slim)
    return routes


def build_boundary(boundary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(boundary, dict):
        return None
    features = boundary.get("features", [])
    if not features:
        return None
    geometry = features[0].get("geometry") or {}
    if geometry.get("type") != "Polygon":
        return None
    return {
        "type": "Polygon",
        "coordinates": [round_coords(ring) for ring in geometry.get("coordinates", [])],
    }


def build_entries(entries_geo: dict[str, Any] | None, poi_catalog: dict[str, Any] | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(entries_geo, dict):
        for feature in entries_geo.get("features", []):
            props = feature.get("properties", {})
            coord = (feature.get("geometry") or {}).get("coordinates")
            poi_id = str(props.get("poi_id", ""))
            if not poi_id or not isinstance(coord, list):
                continue
            seen.add(poi_id)
            entries.append({
                "poi_id": poi_id,
                "name_zh": props.get("name_zh", ""),
                "kind": props.get("kind", ""),
                "category": props.get("category", ""),
                "coord": round_coord(coord),
            })
    if isinstance(poi_catalog, dict):
        for group_key in ("entries", "parks", "services"):
            for item in poi_catalog.get(group_key, []) or []:
                if not isinstance(item, dict):
                    continue
                poi_id = str(item.get("poi_id") or item.get("id") or "")
                coord = item.get("coord") or item.get("coordinates")
                if not poi_id or poi_id in seen or not isinstance(coord, list):
                    continue
                seen.add(poi_id)
                entries.append({
                    "poi_id": poi_id,
                    "name_zh": item.get("name_zh", ""),
                    "kind": item.get("kind", group_key),
                    "category": item.get("category", group_key),
                    "coord": round_coord(coord),
                })
    return entries


def build_environment(dashboard: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(dashboard, dict):
        return {
            "data_generated_at": None,
            "field_specs": [],
            "risk_thresholds": {},
            "cells": [],
            "routes": {},
            "missing_rate": {},
            "excluded_fields": [],
        }
    routes_by_id: dict[str, Any] = {}
    for route in dashboard.get("routes", []) or []:
        route_id = route.get("route_id")
        if not isinstance(route_id, str):
            continue
        routes_by_id[route_id] = {
            "exposure": route.get("exposure", {}),
            "risk": route.get("risk", {}),
            "overall_risk": route.get("overall_risk", "unknown"),
            "missing_fields": route.get("missing_fields", []),
            "cell_ids": route.get("cell_ids", []),
        }
    return {
        "data_generated_at": dashboard.get("data_generated_at"),
        "field_specs": dashboard.get("field_specs", []),
        "risk_thresholds": dashboard.get("risk_thresholds", {}),
        "cells": dashboard.get("cells", []),
        "routes": routes_by_id,
        "missing_rate": dashboard.get("missing_rate", {}),
        "excluded_fields": dashboard.get("excluded_fields", []),
    }


def profile_grid() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for mode in MODES:
        for band in BANDS:
            for pref_key, pref_labels in PREFERENCE_SETS.items():
                for origin_key, origin in ORIGINS.items():
                    profiles.append({
                        "profile_key": f"{mode}__{band}__{pref_key}__{origin_key}",
                        "mode": mode,
                        "band": band,
                        "preferences": list(pref_labels),
                        "origin": {"origin_key": origin_key, **origin},
                    })
    return profiles


def build_recommendations(
    catalog: Any,
    dashboard: Any,
    access_cases: Any,
    poi_catalog: Any,
    weights: Any,
) -> tuple[dict[str, Any], bool]:
    """Call the parallel ``evaluation`` package if importable; degrade otherwise."""
    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))
    profiles = profile_grid()
    try:
        # ``evaluation`` is a namespace package; ``recommend`` is the submodule
        # and ``recommend.recommend`` the callable pipeline entry point.
        from evaluation.recommend import recommend  # type: ignore[import-not-found]
    except ImportError:
        return {}, False
    cases = access_cases.get("cases", []) if isinstance(access_cases, dict) else []
    # resolve_band treats ints as km; only aliases/labels map to the band index.
    band_aliases = {"band1": "short", "band2": "medium", "band3": "long"}
    responses: dict[str, Any] = {}
    first_error: str | None = None
    for profile in profiles:
        request = {
            "sport": profile["mode"],
            "distance_band": band_aliases[str(profile["band"])],
            "origin": profile["origin"]["coord"],
            "origin_name": profile["origin"]["name_zh"],
            "preferences": profile["preferences"],
            "limit": 10,
        }
        try:
            response = recommend(
                request,
                catalog=catalog,
                dashboard=dashboard,
                access=cases,
                pois=poi_catalog,
                weights=weights if isinstance(weights, dict) else None,
            )
        except (TypeError, KeyError, ValueError, AttributeError, RuntimeError, OSError) as exc:
            if first_error is None:
                first_error = f"{type(exc).__name__}: {exc}"
            continue
        if isinstance(response, dict):
            responses[profile["profile_key"]] = response
    if first_error is not None:
        failed = len(profiles) - len(responses)
        print(f"[warn] evaluation.recommend failed for {failed} profiles ({first_error})", file=sys.stderr)
    return responses, len(responses) == len(profiles)


BASELINE_NOTE_ZH = (
    "目录级基线评分：仅环境健康与路线质量两维可离线计算，权重按这两维重归一；"
    "运动匹配、接驳便利与用户偏好依赖一次具体请求（运动方式、距离带、起点、偏好），"
    "切到「帮我推荐」并填写起点后这三维才会出现，此处不代入任何假设值。"
)


def build_route_scores(
    catalog: Any,
    dashboard: Any,
    weights: Any,
) -> tuple[dict[str, Any], bool]:
    """Request-independent score block for every catalog route, keyed by route_id.

    ``build_recommendations`` only scores routes that survive a recommendation
    request, and the page kept those scores in a per-request map that is cleared on
    every flow change. A route opened in browse mode -- or any route outside the
    current candidate set -- therefore had no breakdown at all, and the detail panel
    printed "评估模块结果缺失" even though the 54-cell dashboard was complete and
    every field's missing rate was 0.0.

    The three request-dependent dimensions are deliberately left unavailable rather
    than filled with the route's own mode and band: that would score a route against
    itself, return a trivially perfect match, and report a number no request ever
    asked for. ``combine_dimensions`` renormalises over the scorable dimensions, so
    leaving them null is the honest equivalent of ``scored_catalog_summary``.
    """
    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))
    try:
        from evaluation import scorer  # type: ignore[import-not-found]
    except ImportError:
        return {}, False
    routes = catalog.get("routes") if isinstance(catalog, dict) else None
    route_list = [item for item in routes if isinstance(item, dict)] if isinstance(routes, list) else []
    if not route_list:
        return {}, False
    dash_routes = scorer.dashboard_route_map(dashboard)
    thresholds = dashboard.get("risk_thresholds") if isinstance(dashboard, dict) else None
    thresholds_map: dict[str, Any] = thresholds if isinstance(thresholds, dict) else {}
    weights_map: dict[str, Any] = weights if isinstance(weights, dict) else {}
    null_dimension: dict[str, Any] = {
        "score": None,
        "status": "unavailable",
        "contributors": [],
        "missing_indicators": [],
        "reason_zh": "需要一次具体请求才能计算，基线评分不代入假设值。",
    }
    scores: dict[str, Any] = {}
    for route in route_list:
        route_id = route.get("route_id")
        if not isinstance(route_id, str):
            continue
        dash_route = dash_routes.get(route_id)
        exposure_raw = dash_route.get("exposure") if dash_route is not None else None
        exposure: dict[str, Any] = exposure_raw if isinstance(exposure_raw, dict) else {}
        environment = scorer.score_environment(exposure)
        quality = scorer.score_route_quality(route)
        total, breakdown = scorer.combine_dimensions(
            {
                "environment_health": environment,
                "sport_match": dict(null_dimension),
                "access_convenience": dict(null_dimension),
                "route_quality": quality,
                "user_preference": dict(null_dimension),
            },
            weights_map,
        )
        risk = scorer.route_risk(dash_route, exposure, thresholds_map)
        reliability, reliability_fields = scorer.data_reliability(exposure)
        scored = [key for key, info in breakdown.items() if info.get("score") is not None]
        scores[route_id] = {
            "score_breakdown": breakdown,
            "total_score": total,
            "overall_risk": risk["overall_risk"],
            "risk_pause": bool(risk["risk_pause"]),
            "risk_fields": risk["field_risk"],
            "data_reliability": reliability,
            "data_reliability_fields": reliability_fields,
            "scored_dimensions": scored,
            "excluded_dimensions": sorted(set(breakdown) - set(scored)),
            "missing_fields": sorted({str(k) for k in environment.get("missing_indicators", [])}),
            "note_zh": BASELINE_NOTE_ZH,
            "provenance": "deterministic_computation",
        }
    return scores, len(scores) == len(route_list)


def sha256_of_json(data: Any) -> str:
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def normalize_weights(weights: Any) -> dict[str, Any]:
    """The weights document may nest the five dimensions under a ``weights`` key."""
    if isinstance(weights, dict):
        block = weights.get("weights", weights)
        if isinstance(block, dict):
            return block
    return {}


def weights_sha(weights_block: dict[str, Any]) -> str:
    """Prefer the evaluation package's canonical hash so both artifacts agree."""
    try:
        from evaluation.weights import weights_sha256  # type: ignore[import-not-found]

        return str(weights_sha256({k: float(v) for k, v in weights_block.items()}))
    except (ImportError, TypeError, ValueError, AttributeError):
        return sha256_of_json(weights_block)


def build_payload(
    catalog: dict[str, Any] | None,
    boundary_payload: dict[str, Any] | None,
    routes: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    environment: dict[str, Any],
    recommendations: dict[str, Any],
    route_scores: dict[str, Any],
    access_cases: Any,
    weights: Any,
    missing_inputs: list[str],
) -> dict[str, Any]:
    district = (catalog or {}).get("district") or {}
    cases = access_cases.get("cases", []) if isinstance(access_cases, dict) else []
    source_by_input = {
        "route_catalog.json": "xuhui_route_builder/data/web/route_catalog.json",
        "xuhui_routes.geojson": "xuhui_route_builder/data/web/xuhui_routes.geojson",
        "xuhui_boundary.geojson": "xuhui_route_builder/data/web/xuhui_boundary.geojson",
        "xuhui_entries.geojson": "xuhui_route_builder/data/web/xuhui_entries.geojson",
        "poi_catalog.json": "xuhui_route_builder/data/web/poi_catalog.json",
        "access_cases.json": "xuhui_route_builder/data/web/access_cases.json",
        "environment_dashboard.json": "xuhui_route_builder/data/web/environment_dashboard.json",
        "default_weights.json": "evaluation_model_qwen/config/default_weights.json",
        "evaluation_package": "evaluation package (workspace/source/evaluation)",
    }
    missing = set(missing_inputs)
    sources = [path for name, path in source_by_input.items() if name not in missing]
    licences: list[str] = []
    for holder in (district, boundary_payload or {}):
        licence = holder.get("licence") if isinstance(holder, dict) else None
        if isinstance(licence, str) and licence not in licences:
            licences.append(licence)
    if isinstance(access_cases, dict) and isinstance(access_cases.get("licence"), str):
        licences.append(access_cases["licence"])
    notes = [
        "所有几何坐标来自本 run 的确定性路网生成，未调用任何在线路径规划 API。",
        "接驳时间为确定性估算（直线距离 x 绕行系数 / 假设速度），页面会如实标注。",
        "缺失输入不会被伪造，见 missing_inputs 与 partial_data。",
    ]
    return {
        "schema_version": 1,
        "run_id": (catalog or {}).get("run_id") or run_id_from_manifest(),
        "generated_at": utc_now_iso(),
        "crs": CRS,
        "district": district,
        "boundary": boundary_payload,
        "routes": routes,
        "entries": entries,
        "environment": environment,
        "recommendations": recommendations,
        "route_scores": route_scores,
        "access_cases": cases,
        "weights": weights if isinstance(weights, dict) else {},
        "weights_sha256": weights_sha(weights if isinstance(weights, dict) else {}),
        "provenance": {
            "sources": sources,
            "licences": licences or ["ODbL 1.0 (OpenStreetMap 衍生数据)"],
            "notes": notes,
        },
        "missing_inputs": missing_inputs,
        "partial_data": bool(missing_inputs),
    }


def run_id_from_manifest() -> str:
    manifest = load_json(RUN_ROOT / "run_manifest.json")
    if isinstance(manifest, dict) and isinstance(manifest.get("run_id"), str):
        return manifest["run_id"]
    return RUN_ROOT.name


def build_research_harness(
    payload: dict[str, Any], missing_inputs: list[str]
) -> dict[str, Any]:
    goal = load_json(EXPERIMENTS_DIR / "research_goal.json") or {}
    hypotheses_doc = load_json(EXPERIMENTS_DIR / "hypotheses.json") or {}
    metrics_doc = load_json(EXPERIMENTS_DIR / "evaluation_metrics.json") or {}
    hypothesis_list = hypotheses_doc.get("hypotheses") or []
    first = hypothesis_list[0] if hypothesis_list else {}
    routes = payload.get("routes") or []
    mode_counts: dict[str, int] = {}
    band_counts: dict[str, int] = {}
    for route in routes:
        mode_counts[route.get("mode", "?")] = mode_counts.get(route.get("mode", "?"), 0) + 1
        band_counts[route.get("band", "?")] = band_counts.get(route.get("band", "?"), 0) + 1
    environment = payload.get("environment") or {}
    metrics_summary: dict[str, Any] = {"available": bool(metrics_doc)}
    if isinstance(metrics_doc, dict) and metrics_doc:
        metrics_summary["scoring_dimensions"] = [
            d.get("dimension") for d in metrics_doc.get("scoring_dimensions", [])
        ]
        metrics_summary["reliability_multipliers"] = metrics_doc.get("reliability_multipliers", {})
        metrics_summary["missing_metric_score"] = metrics_doc.get("missing_metric_score")
    status = "completed" if not missing_inputs else "partial"
    return {
        "run_id": payload.get("run_id") or run_id_from_manifest(),
        "generated_at": payload.get("generated_at"),
        "status": status,
        "research_question": goal.get("question", ""),
        "hypothesis": first.get("statement", ""),
        "product": {
            "name": "xuhui-healthy-routes-local",
            "entry": "publish/local-product/index.html",
            "serve_hint": "python -m http.server rooted at publish/local-product",
            "offline": True,
            "external_runtime_requests": False,
            "renderer": "hand-written canvas equirectangular projection, vanilla ES2020 modules",
        },
        "metrics": metrics_summary,
        "routes_summary": {
            "route_count": len(routes),
            "mode_counts": mode_counts,
            "band_counts": band_counts,
        },
        "environment_summary": {
            "available": bool(environment.get("cells")),
            "cell_count": len(environment.get("cells") or []),
            "missing_rate": environment.get("missing_rate", {}),
            "excluded_fields": environment.get("excluded_fields", []),
            "data_generated_at": environment.get("data_generated_at"),
        },
        "report_paths": [
            "workspace/source/web/data/app_payload.json",
            "publish/research_harness_latest.json",
            "publish/local-product/index.html",
            "publish/local-product/data/app_payload.json",
        ],
        "data_generated_at": environment.get("data_generated_at"),
        "provider": "qoder_session",
        "model_name": "qwen3.8-max",
        "dashscope_api_used": False,
        "missing_inputs": missing_inputs,
    }


def publish_local_product(payload: dict[str, Any]) -> None:
    LOCAL_PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js", "map.js"):
        src = SOURCE_WEB_DIR / name
        if src.exists():
            shutil.copy2(src, LOCAL_PRODUCT_DIR / name)
        else:
            print(f"[warn] web source missing: {name}", file=sys.stderr)
    data_dir = LOCAL_PRODUCT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    write_json(data_dir / "app_payload.json", payload)
    web_data_dir = data_dir / "web"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "route_catalog.json",
        "xuhui_routes.geojson",
        "xuhui_boundary.geojson",
        "environment_dashboard.json",
    ):
        src = WEB_DATA_DIR / name
        if src.exists():
            shutil.copy2(src, web_data_dir / name)
    harness_src = PUBLISH_DIR / "research_harness_latest.json"
    if harness_src.exists():
        shutil.copy2(harness_src, web_data_dir / "research_harness_latest.json")
    # Mirror the same data/web tree next to the dev copy so workspace/source/web
    # can be served standalone with identical fetch paths.
    dev_web_data = SOURCE_WEB_DIR / "data" / "web"
    dev_web_data.mkdir(parents=True, exist_ok=True)
    for item in web_data_dir.iterdir():
        shutil.copy2(item, dev_web_data / item.name)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))
    catalog = load_json(WEB_DATA_DIR / "route_catalog.json")
    routes_geo = load_json(WEB_DATA_DIR / "xuhui_routes.geojson")
    boundary_geo = load_json(WEB_DATA_DIR / "xuhui_boundary.geojson")
    entries_geo = load_json(WEB_DATA_DIR / "xuhui_entries.geojson")
    poi_catalog = load_json(WEB_DATA_DIR / "poi_catalog.json")
    access_cases = load_json(WEB_DATA_DIR / "access_cases.json")
    dashboard = load_json(WEB_DATA_DIR / "environment_dashboard.json")
    weights = load_json(SOURCE_ROOT / "evaluation_model_qwen" / "config" / "default_weights.json")

    file_inputs = {
        "route_catalog.json": catalog,
        "xuhui_routes.geojson": routes_geo,
        "xuhui_boundary.geojson": boundary_geo,
        "xuhui_entries.geojson": entries_geo,
        "poi_catalog.json": poi_catalog,
        "access_cases.json": access_cases,
        "environment_dashboard.json": dashboard,
        "default_weights.json": weights,
    }
    missing_inputs: list[str] = [name for name, value in file_inputs.items() if value is None]

    routes = build_routes(catalog, routes_geo)
    if catalog is not None and routes_geo is not None and not routes:
        print("[warn] catalog and geojson present but produced 0 routes", file=sys.stderr)
    boundary_payload = build_boundary(boundary_geo)
    entries = build_entries(entries_geo, poi_catalog)
    environment = build_environment(dashboard)
    weights_block = normalize_weights(weights)
    recommendations, rec_complete = build_recommendations(
        catalog, dashboard, access_cases, poi_catalog, weights_block or None
    )
    route_scores, scores_complete = build_route_scores(catalog, dashboard, weights_block)
    if not rec_complete or not scores_complete:
        if "evaluation_package" not in missing_inputs:
            missing_inputs.append("evaluation_package")
    missing_inputs = [name for name in MANDATORY_INPUTS if name in set(missing_inputs)]

    payload = build_payload(
        catalog=catalog,
        boundary_payload=boundary_payload,
        routes=routes,
        entries=entries,
        environment=environment,
        recommendations=recommendations,
        route_scores=route_scores,
        access_cases=access_cases,
        weights=weights_block,
        missing_inputs=missing_inputs,
    )
    write_json(SOURCE_WEB_DIR / "data" / "app_payload.json", payload)

    harness = build_research_harness(payload, missing_inputs)
    if not harness.get("data_generated_at"):
        generated = (catalog or {}).get("generated_at")
        harness["data_generated_at"] = generated if isinstance(generated, str) else None
    write_json(PUBLISH_DIR / "research_harness_latest.json", harness)

    publish_local_product(payload)

    print(json.dumps({
        "status": harness["status"],
        "route_count": len(routes),
        "entry_count": len(entries),
        "recommendation_count": len(recommendations),
        "environment_cells": len(environment.get("cells") or []),
        "missing_inputs": missing_inputs,
        "partial_data": payload["partial_data"],
        "payload_bytes": (SOURCE_WEB_DIR / "data" / "app_payload.json").stat().st_size,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
