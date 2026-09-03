"""Recommendation pipeline: filtering, scoring, ranking and response assembly (offline only)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import scorer
from .weights import WeightsError, load_weights, weights_sha256

logger = logging.getLogger("evaluation.recommend")

SOURCE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = SOURCE_DIR / "xuhui_route_builder" / "data" / "web"
CATALOG_PATH = WEB_DIR / "route_catalog.json"
DASHBOARD_PATH = WEB_DIR / "environment_dashboard.json"
ACCESS_PATH = WEB_DIR / "access_cases.json"
POIS_PATH = WEB_DIR / "poi_catalog.json"
ENTRIES_PATH = WEB_DIR / "xuhui_entries.geojson"

SPORTS: tuple[str, ...] = ("walk", "run", "bike")

#: Mirrors workspace/source/routes/generator.py BANDS_KM and catalog.py
#: BAND_LABELS, read in this run; used only as a fallback when the catalog
#: file itself is unavailable.
DEFAULT_BANDS_KM: dict[str, tuple[tuple[float, float], ...]] = {
    "walk": ((0.5, 2.0), (2.0, 3.5), (3.5, 5.0)),
    "run": ((1.0, 5.0), (5.0, 10.0), (10.0, 15.0)),
    "bike": ((5.0, 10.0), (10.0, 20.0), (20.0, 30.0)),
}
DEFAULT_BAND_LABELS_ZH: dict[str, tuple[str, ...]] = {
    "walk": ("轻松短程", "中等距离", "长距健行"),
    "run": ("短程快跑", "中距离跑", "长距离跑"),
    "bike": ("通勤骑行", "中距骑行", "长距骑行"),
}
BAND_ALIASES: dict[str, int] = {
    "short": 0,
    "medium": 1,
    "mid": 1,
    "long": 2,
    "短程": 0,
    "中等": 1,
    "中距": 1,
    "长距": 2,
    "长程": 2,
}

KNOWN_REQUEST_KEYS: frozenset[str] = frozenset(
    {
        "sport",
        "distance_band",
        "origin",
        "origin_name",
        "preferences",
        "max_access_min",
        "avoid_risk_pause",
        "prefer_loop",
        "limit",
    }
)

ROUTE_SUMMARY_KEYS: tuple[str, ...] = (
    "route_id",
    "name_zh",
    "mode",
    "mode_label",
    "kind",
    "kind_label",
    "band",
    "band_label",
    "band_label_zh",
    "actual_distance_m",
    "target_distance_m",
    "distance_error",
    "duration_min",
    "area",
    "area_name_zh",
    "start",
    "end",
    "status",
    "park_relation",
    "nearby_services",
    "coordinate_count",
)


class InvalidRequestError(ValueError):
    """Raised when the request cannot be interpreted (e.g. missing or invalid sport)."""


def load_json(path: Path) -> Any | None:
    """Read one JSON artifact, returning None when it is missing or malformed."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("json decode failed for %s", path.name)
        return None


def load_access_list(payload: Any) -> list[Any]:
    """access_cases.json is a dict with a cases list; a bare list is also accepted."""
    if isinstance(payload, dict):
        cases = payload.get("cases")
        return cases if isinstance(cases, list) else []
    if isinstance(payload, list):
        return payload
    return []


def load_default_inputs() -> dict[str, Any]:
    """Load all four web artifacts once, recording which are missing."""
    catalog = load_json(CATALOG_PATH)
    dashboard = load_json(DASHBOARD_PATH)
    access_payload = load_json(ACCESS_PATH)
    pois = load_json(POIS_PATH)
    missing: list[str] = []
    if not isinstance(catalog, dict):
        missing.append("route_catalog.json")
    if not isinstance(dashboard, dict):
        missing.append("environment_dashboard.json")
    if access_payload is None:
        missing.append("access_cases.json")
    if not isinstance(pois, dict):
        missing.append("poi_catalog.json")
    return {
        "catalog": catalog if isinstance(catalog, dict) else None,
        "dashboard": dashboard if isinstance(dashboard, dict) else None,
        "access": load_access_list(access_payload),
        "pois": pois if isinstance(pois, dict) else None,
        "missing_inputs": missing,
    }


def _catalog_routes(catalog: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(catalog, Mapping):
        return []
    routes = catalog.get("routes")
    if not isinstance(routes, list):
        return []
    return [route for route in routes if isinstance(route, dict)]


def _band_tables(catalog: Mapping[str, Any] | None, sport: str) -> tuple[tuple[str, ...], tuple[tuple[float, float], ...]]:
    labels = list(DEFAULT_BAND_LABELS_ZH.get(sport, ()))
    ranges = list(DEFAULT_BANDS_KM.get(sport, ()))
    if isinstance(catalog, Mapping):
        routes = _catalog_routes(catalog)
        seen: dict[int, str] = {}
        for route in routes:
            if route.get("mode") != sport:
                continue
            band = route.get("band")
            label = route.get("band_label_zh")
            if isinstance(band, int) and isinstance(label, str):
                seen[band] = label
        if seen:
            #: Labels must stay index-aligned with the band table even when the
            #: catalog only contains routes for some bands of this mode.
            size = max(len(labels), max(seen) + 1)
            labels = [
                seen.get(index)
                or (labels[index] if index < len(labels) else f"未命名距离带{index}")
                for index in range(size)
            ]
        bands_km = catalog.get("distance_bands_km")
        if isinstance(bands_km, dict):
            sport_bands = bands_km.get(sport)
            if isinstance(sport_bands, list) and sport_bands:
                parsed: list[tuple[float, float]] = []
                for pair in sport_bands:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        low = scorer.as_float(pair[0])
                        high = scorer.as_float(pair[1])
                        if low is not None and high is not None:
                            parsed.append((low, high))
                if parsed:
                    ranges = parsed
    return tuple(labels), tuple(ranges)


def resolve_band(
    sport: str, distance_band: Any, catalog: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Resolve the requested band into an index/label/km-range filter spec."""
    if distance_band is None:
        return None
    labels, ranges = _band_tables(catalog, sport)

    def spec(index: int | None, low: float, high: float, label: str | None) -> dict[str, Any]:
        return {
            "index": index,
            "label_zh": label,
            "range_km": (low, high),
            "target_m": (low + high) / 2.0 * 1000.0,
            "raw": distance_band,
            "provenance": "band_table:catalog_or_module_default",
        }

    if isinstance(distance_band, (list, tuple)) and len(distance_band) == 2:
        low = scorer.as_float(distance_band[0])
        high = scorer.as_float(distance_band[1])
        if low is None or high is None or low > high:
            raise InvalidRequestError(
                f"distance_band 数值对无效: {distance_band!r}，应为 (low_km, high_km)"
            )
        return spec(None, low, high, None)
    if isinstance(distance_band, (int, float)) and not isinstance(distance_band, bool):
        km = float(distance_band)
        for index, (low, high) in enumerate(ranges):
            if low <= km < high:
                label = labels[index] if index < len(labels) else None
                return spec(index, low, high, label)
        raise InvalidRequestError(f"distance_band={km:g} km 不在 {sport} 的任何距离带内")
    if isinstance(distance_band, str):
        text = distance_band.strip()
        if not text:
            return None
        for index, label in enumerate(labels):
            if text == label:
                low, high = ranges[index] if index < len(ranges) else (0.0, 0.0)
                return spec(index, low, high, label)
        lowered = text.lower()
        if lowered in BAND_ALIASES:
            index = BAND_ALIASES[lowered]
            if index < len(ranges):
                low, high = ranges[index]
                label = labels[index] if index < len(labels) else None
                return spec(index, low, high, label)
        digits = text.replace("km", "").replace("公里", "").replace("千米", "").strip()
        try:
            km = float(digits)
        except ValueError:
            raise InvalidRequestError(
                f"distance_band={text!r} 无法识别，{sport} 可用距离带：{'、'.join(labels)}"
            ) from None
        for index, (low, high) in enumerate(ranges):
            if low <= km < high:
                label = labels[index] if index < len(labels) else None
                return spec(index, low, high, label)
        raise InvalidRequestError(f"distance_band={text!r} 不在 {sport} 的任何距离带内")
    raise InvalidRequestError(f"distance_band 类型无效: {type(distance_band).__name__}")


def band_matches(route: Mapping[str, Any], band_spec: Mapping[str, Any] | None) -> bool:
    """True when a route satisfies the resolved band filter."""
    if band_spec is None:
        return True
    index = band_spec.get("index")
    if index is not None:
        return route.get("band") == index
    low, high = band_spec["range_km"]
    distance = scorer.as_float(route.get("actual_distance_m"))
    if distance is None:
        return False
    return low * 1000.0 <= distance <= high * 1000.0


def _poi_lists(pois: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    groups: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(pois, Mapping):
        return groups
    for category in ("entries", "parks", "services"):
        items = pois.get(category)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    groups.append((category, item))
    return groups


def resolve_origin(
    request: Mapping[str, Any],
    pois: Mapping[str, Any] | None,
    access: Sequence[Any],
) -> tuple[list[float] | None, str | None, str]:
    """Resolve the request origin to [lon, lat]; returns (coord, name, provenance)."""
    name = request.get("origin_name")
    name = str(name).strip() if isinstance(name, str) and name.strip() else None
    origin = request.get("origin")
    if isinstance(origin, (list, tuple)) and len(origin) >= 2:
        lon = scorer.as_float(origin[0])
        lat = scorer.as_float(origin[1])
        if lon is not None and lat is not None and -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0:
            return [lon, lat], name, "request_origin"
        if origin:
            raise InvalidRequestError(f"origin 坐标无效: {origin!r}")
    if name is None:
        return None, None, "absent"
    for category, item in _poi_lists(pois):
        if item.get("name_zh") == name:
            coord = item.get("coord")
            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                return [float(coord[0]), float(coord[1])], name, f"poi_catalog:{category}:{item.get('poi_id')}"
    for category, item in _poi_lists(pois):
        poi_name = str(item.get("name_zh", ""))
        if poi_name and (name in poi_name or poi_name in name):
            coord = item.get("coord")
            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                return [float(coord[0]), float(coord[1])], poi_name, f"poi_catalog_fuzzy:{category}:{item.get('poi_id')}"
    for case in access:
        if not isinstance(case, dict):
            continue
        case_origin = case.get("origin")
        if isinstance(case_origin, dict) and case_origin.get("name_zh") == name:
            coord = case_origin.get("coord")
            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                return [float(coord[0]), float(coord[1])], name, f"access_cases:{case.get('case_id')}"
    return None, name, "unresolved"


def global_risk(dashboard: Mapping[str, Any] | None) -> dict[str, Any]:
    """District-level risk summary across all inside-district dashboard cells."""
    if not isinstance(dashboard, Mapping):
        return {
            "level": "unknown",
            "pause_fields": [],
            "stop_fields": [],
            "as_of": None,
            "provenance": "environment_dashboard_missing",
        }
    thresholds = dashboard.get("risk_thresholds")
    cells = dashboard.get("cells")
    worst: dict[str, str] = {}
    if isinstance(thresholds, dict) and isinstance(cells, list):
        for field, spec in thresholds.items():
            if not isinstance(spec, dict):
                continue
            levels: list[str] = []
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                values = cell.get("values")
                if not isinstance(values, dict):
                    continue
                item = values.get(field)
                value = scorer.as_float(item.get("value")) if isinstance(item, dict) else None
                levels.append(scorer.field_severity(value, spec))
            considered = [level for level in levels if level != "unknown"]
            worst[str(field)] = scorer.worst_severity(considered) if considered else "unknown"
    level = scorer.worst_severity(list(worst.values())) if worst else "unknown"
    pause_fields = sorted(key for key, value in worst.items() if value in ("pause", "stop"))
    stop_fields = sorted(key for key, value in worst.items() if value == "stop")
    return {
        "level": level,
        "pause_fields": pause_fields,
        "stop_fields": stop_fields,
        "as_of": dashboard.get("data_generated_at") or dashboard.get("generated_at"),
        "provenance": "deterministic_computation:worst_over_dashboard_cells",
    }


def normalize_profile(
    request: Mapping[str, Any],
    catalog: Mapping[str, Any] | None,
    pois: Mapping[str, Any] | None,
    access: Sequence[Any],
) -> dict[str, Any]:
    """Validate the request and echo it back as a normalised profile."""
    sport = request.get("sport")
    if not isinstance(sport, str) or sport.strip().lower() not in SPORTS:
        raise InvalidRequestError(
            f"sport 必填且必须是 {'|'.join(SPORTS)}，收到 {sport!r}"
        )
    sport = sport.strip().lower()
    band_spec = resolve_band(sport, request.get("distance_band"), catalog)
    origin_coord, origin_name, origin_provenance = resolve_origin(request, pois, access)
    preferences_raw = request.get("preferences") or []
    if isinstance(preferences_raw, str):
        preferences = [preferences_raw]
    elif isinstance(preferences_raw, Sequence):
        preferences = [str(tag) for tag in preferences_raw]
    else:
        raise InvalidRequestError(f"preferences 应为字符串列表，收到 {type(preferences_raw).__name__}")
    limit_value = scorer.as_float(request.get("limit", 10))
    limit = int(limit_value) if limit_value is not None and limit_value >= 1 else 10
    max_access_raw = scorer.as_float(request.get("max_access_min"))
    prefer_loop = request.get("prefer_loop")
    return {
        "sport": sport,
        "distance_band": request.get("distance_band"),
        "band_label_zh": band_spec.get("label_zh") if band_spec else None,
        "band_range_km": list(band_spec["range_km"]) if band_spec else None,
        "band_target_m": band_spec.get("target_m") if band_spec else None,
        "origin": origin_coord,
        "origin_name": origin_name,
        "origin_provenance": origin_provenance,
        "preferences": preferences,
        "max_access_min": max_access_raw,
        "avoid_risk_pause": bool(request.get("avoid_risk_pause", True)),
        "prefer_loop": bool(prefer_loop) if isinstance(prefer_loop, bool) else None,
        "limit": limit,
        "ignored_request_keys": sorted(
            str(key) for key in request.keys() if str(key) not in KNOWN_REQUEST_KEYS
        ),
    }


def score_candidates(
    request: Mapping[str, Any],
    catalog: Mapping[str, Any] | None = None,
    dashboard: Mapping[str, Any] | None = None,
    access: Sequence[Any] | None = None,
    pois: Mapping[str, Any] | None = None,
    weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Shared pipeline: validate, filter, score and rank nothing yet; strategies sort later."""
    if catalog is None or dashboard is None or access is None or pois is None:
        defaults = load_default_inputs()
        catalog = defaults["catalog"] if catalog is None else catalog
        dashboard = defaults["dashboard"] if dashboard is None else dashboard
        access = defaults["access"] if access is None else access
        pois = defaults["pois"] if pois is None else pois
    access_list: Sequence[Any] = access if access is not None else []
    profile = normalize_profile(request, catalog, pois, access_list)
    sport = profile["sport"]
    band_spec = resolve_band(sport, profile["distance_band"], catalog)
    origin_coord = profile["origin"]
    request_ctx = {
        "sport": sport,
        "band_range_km": tuple(band_spec["range_km"]) if band_spec else None,
        "prefer_loop": profile["prefer_loop"],
        "preferences": profile["preferences"],
        "origin_name": profile["origin_name"],
    }
    weights_map: Mapping[str, float] = weights if weights is not None else load_weights()[0]
    dash_routes = scorer.dashboard_route_map(dashboard)
    thresholds_raw = dashboard.get("risk_thresholds") if isinstance(dashboard, Mapping) else None
    thresholds: Mapping[str, Any] = thresholds_raw if isinstance(thresholds_raw, dict) else {}

    routes = _catalog_routes(catalog)
    removed = {"sport": 0, "status": 0, "band": 0, "risk": 0, "max_access_min": 0}
    candidates: list[dict[str, Any]] = []
    for route in routes:
        if route.get("mode") != sport:
            removed["sport"] += 1
            continue
        if route.get("status") != "accepted":
            removed["status"] += 1
            continue
        if not band_matches(route, band_spec):
            removed["band"] += 1
            continue
        dash_route = dash_routes.get(str(route.get("route_id", "")))
        scored = scorer.score_route(route, dash_route, origin_coord, request_ctx, weights_map, thresholds)
        if profile["avoid_risk_pause"] and scored["overall_risk"] in ("pause", "stop"):
            removed["risk"] += 1
            continue
        access_min = scored["estimated_access_min"]
        if profile["max_access_min"] is not None:
            if access_min is None or access_min > float(profile["max_access_min"]):
                removed["max_access_min"] += 1
                continue
        candidate: dict[str, Any] = {key: route.get(key) for key in ROUTE_SUMMARY_KEYS}
        candidate.update(scored)
        candidates.append(candidate)

    partial_data = (
        dashboard is None
        or profile["origin_provenance"] == "unresolved"
        or any(item["missing_fields"] for item in candidates)
        or any(
            item["score_breakdown"]["environment_health"]["status"] != "ok"
            or float(item["data_reliability"]) < 1.0
            for item in candidates
        )
    )
    return {
        "profile": profile,
        "risk": global_risk(dashboard),
        "candidates": candidates,
        "removed": removed,
        "route_total": len(routes),
        "band_spec": band_spec,
        "partial_data": partial_data,
        "data_generated_at": (
            dashboard.get("data_generated_at") if isinstance(dashboard, Mapping) else None
        )
        or (catalog.get("generated_at") if isinstance(catalog, Mapping) else None),
        "weights": dict(weights_map),
        "missing_inputs": (
            [] if dashboard is not None else ["environment_dashboard.json"]
        )
        + ([] if catalog is not None else ["route_catalog.json"]),
    }


def _empty_reason(profile: Mapping[str, Any], removed: Mapping[str, int], route_total: int) -> str:
    parts = [f"运动方式 {profile['sport']}"]
    if profile.get("band_label_zh"):
        parts.append(f"距离带“{profile['band_label_zh']}”")
    elif profile.get("band_range_km"):
        parts.append(f"距离范围 {profile['band_range_km'][0]:g}–{profile['band_range_km'][1]:g} km")
    if profile.get("avoid_risk_pause"):
        parts.append("风险不达到暂停/停止")
    if profile.get("max_access_min") is not None:
        parts.append(f"接驳不超过 {profile['max_access_min']:g} 分钟")
    detail = "、".join(f"{key} 剔除 {value} 条" for key, value in removed.items() if value)
    reason = f"目录共 {route_total} 条路线，没有路线同时满足：" + "、".join(parts) + "。"
    if detail:
        reason += f"（{detail}）"
    if profile.get("origin_provenance") == "unresolved":
        reason += f"起点“{profile.get('origin_name')}”未能解析，接驳过滤不可用。"
    reason += "建议放宽距离带、关闭 avoid_risk_pause 或更换起点后重试。"
    return reason


def assemble_response(
    prepared: Mapping[str, Any],
    strategy: str,
    sort_key: Callable[[Mapping[str, Any]], tuple[Any, ...]],
    sha: str,
    offline: bool,
    ignored_kwargs: Sequence[str],
) -> dict[str, Any]:
    """Sort scored candidates per strategy and build the final response dict."""
    candidates = sorted(prepared["candidates"], key=sort_key)
    limit = int(prepared["profile"]["limit"])
    candidates = candidates[:limit]
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
        candidate["recommendation_reason_zh"] = scorer.recommendation_reason_zh(candidate, rank)
        candidate["strategy"] = strategy
    profile = prepared["profile"]
    ignored = sorted(set(profile["ignored_request_keys"]) | set(ignored_kwargs))
    empty_reason = None if candidates else _empty_reason(profile, prepared["removed"], prepared["route_total"])
    return {
        "version": 1,
        "strategy": strategy,
        "profile": profile,
        "risk": prepared["risk"],
        "data_generated_at": prepared["data_generated_at"],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "primary": candidates[0] if candidates else None,
        "alternatives": candidates[1:3],
        "weights": prepared["weights"],
        "weights_sha256": sha,
        "filters_applied": {
            "sport": profile["sport"],
            "status": "accepted",
            "distance_band": profile.get("band_label_zh")
            or profile.get("band_range_km")
            or None,
            "avoid_risk_pause": profile["avoid_risk_pause"],
            "max_access_min": profile.get("max_access_min"),
            "removed_counts": dict(prepared["removed"]),
            "route_total": prepared["route_total"],
        },
        "empty_reason": empty_reason,
        "partial_data": bool(prepared["partial_data"]),
        "missing_inputs": list(prepared["missing_inputs"]),
        "offline": bool(offline),
        "ignored_request_keys": ignored,
        "provenance": scorer.PROVENANCE,
    }


def model_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    """Rank by total score descending, route_id ascending for determinism."""
    total = candidate.get("total_score")
    return (0.0 if total is None else -float(total), str(candidate.get("route_id", "")))


def access_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    """Rank by estimated access minutes ascending."""
    minutes = candidate.get("estimated_access_min")
    return (float("inf") if minutes is None else float(minutes), str(candidate.get("route_id", "")))


def distance_sort_key(target_m: float | None) -> Callable[[Mapping[str, Any]], tuple[Any, ...]]:
    """Rank by absolute distance to the requested target."""

    def key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
        distance = scorer.as_float(candidate.get("actual_distance_m"))
        if target_m is None:
            return (float("inf") if distance is None else distance, str(candidate.get("route_id", "")))
        if distance is None:
            return (float("inf"), str(candidate.get("route_id", "")))
        return (abs(distance - target_m), str(candidate.get("route_id", "")))

    return key


def resolve_sha(weights: Mapping[str, float] | None) -> tuple[Mapping[str, float], str]:
    """Prefer the on-disk weights file hash; fall back to hashing the given mapping."""
    if weights is None:
        return load_weights()
    try:
        file_weights, sha = load_weights()
    except WeightsError:
        return weights, weights_sha256(dict(weights))
    if dict(file_weights) == dict(weights):
        return weights, sha
    return weights, weights_sha256(dict(weights))


def recommend(
    request: dict[str, Any],
    catalog: Mapping[str, Any] | None = None,
    dashboard: Mapping[str, Any] | None = None,
    access: Sequence[Any] | None = None,
    pois: Mapping[str, Any] | None = None,
    weights: Mapping[str, float] | None = None,
    *,
    offline: bool = True,
    **_ignored: object,
) -> dict[str, Any]:
    """Full five-dimension recommendation; never performs any network call."""
    if not offline:
        #: The contract requires offline mode; refusing avoids any accidental
        #: network dependency instead of silently switching behaviour.
        raise InvalidRequestError("offline=False 不受支持：本模块只进行本地确定性计算")
    if not isinstance(request, Mapping):
        raise InvalidRequestError(f"request 必须是 dict，收到 {type(request).__name__}")
    resolved_weights, sha = resolve_sha(weights)
    prepared = score_candidates(request, catalog, dashboard, access, pois, resolved_weights)
    return assemble_response(
        prepared,
        "model",
        model_sort_key,
        sha,
        offline,
        sorted(str(key) for key in _ignored),
    )
