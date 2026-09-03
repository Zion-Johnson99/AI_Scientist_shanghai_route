"""Adapter surface over the generated route artifacts.

Reads only files produced inside this run; performs no network access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODULE_ROOT: Path = Path(__file__).resolve().parent
CORE_PAIR: tuple[str, str] = ("data/web/route_catalog.json", "data/web/xuhui_routes.geojson")
OPTIONAL_ARTIFACTS: tuple[str, ...] = (
    "data/web/xuhui_entries.geojson",
    "data/web/poi_catalog.json",
    "data/web/access_cases.json",
)


class RouteArtifactError(RuntimeError):
    """Raised when a core route artifact is missing or unreadable."""


@dataclass(frozen=True)
class RouteModuleResult:
    """Immutable summary of the route module artifacts."""

    route_count: int
    mode_counts: dict[str, int]
    kind_counts: dict[str, dict[str, int]]
    bucket_counts: dict[str, int]
    area_counts: dict[str, int]
    accepted_count: int
    needs_review_count: int
    crs: str
    route_ids: tuple[str, ...]
    artifacts: dict[str, int]
    missing_artifacts: tuple[str, ...]


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise RouteArtifactError(f"路线产物缺失: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RouteArtifactError(f"路线产物无法解析: {path.name}") from exc


def load_catalog(root: Path | None = None) -> dict[str, Any]:
    """Return the route catalog payload, raising if the core pair is absent."""
    base = root or MODULE_ROOT
    for relative in CORE_PAIR:
        if not (base / relative).is_file():
            raise RouteArtifactError("核心路线产物缺失（route_catalog.json / xuhui_routes.geojson）")
    payload = _read_json(base / CORE_PAIR[0])
    if not isinstance(payload, dict):
        raise RouteArtifactError("route_catalog.json 顶层不是对象")
    return payload


def load_routes_geojson(root: Path | None = None) -> dict[str, Any]:
    """Return the route FeatureCollection."""
    base = root or MODULE_ROOT
    payload = _read_json(base / CORE_PAIR[1])
    if not isinstance(payload, dict):
        raise RouteArtifactError("xuhui_routes.geojson 顶层不是对象")
    return payload


def build_result(root: Path | None = None) -> RouteModuleResult:
    """Summarise the artifacts and report which optional files are absent."""
    base = root or MODULE_ROOT
    catalog = load_catalog(base)
    routes: list[dict[str, Any]] = list(catalog.get("routes") or [])
    artifacts: dict[str, int] = {}
    for relative in (*CORE_PAIR, *OPTIONAL_ARTIFACTS):
        target = base / relative
        artifacts[relative] = target.stat().st_size if target.is_file() else 0
    missing = tuple(
        relative for relative in OPTIONAL_ARTIFACTS if not (base / relative).is_file()
    )
    accepted = sum(1 for item in routes if item.get("status") == "accepted")
    return RouteModuleResult(
        route_count=int(catalog.get("route_count") or len(routes)),
        mode_counts=dict(catalog.get("mode_counts") or {}),
        kind_counts={k: dict(v) for k, v in (catalog.get("kind_counts") or {}).items()},
        bucket_counts=dict(catalog.get("bucket_counts") or {}),
        area_counts=dict(catalog.get("area_counts") or {}),
        accepted_count=accepted,
        needs_review_count=sum(1 for item in routes if item.get("status") == "needs_review"),
        crs=str(catalog.get("crs") or "unknown"),
        route_ids=tuple(str(item.get("route_id")) for item in routes),
        artifacts=artifacts,
        missing_artifacts=missing,
    )


def as_dict(result: RouteModuleResult) -> dict[str, Any]:
    """Serialise a RouteModuleResult for JSON output."""
    return {
        "route_count": result.route_count,
        "mode_counts": result.mode_counts,
        "kind_counts": result.kind_counts,
        "bucket_counts": result.bucket_counts,
        "area_counts": result.area_counts,
        "accepted_count": result.accepted_count,
        "needs_review_count": result.needs_review_count,
        "crs": result.crs,
        "route_id_count": len(result.route_ids),
        "artifacts": result.artifacts,
        "missing_artifacts": list(result.missing_artifacts),
    }
