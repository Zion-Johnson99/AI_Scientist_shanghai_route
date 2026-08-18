from __future__ import annotations

import argparse
import json
import os
import tempfile
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

from .amap_client import AmapClient
from .baidu_client import BaiduClient
from .config import PROJECT_ROOT, load_settings
from .demo_dataset import build_demo_dataset
from .exporters import (
    build_access_catalog,
    build_candidate_route_catalog,
    build_candidate_route_feature_collection,
    build_feature_collection,
    build_poi_feature_collection,
    build_route_catalog,
    build_route_feature_collection,
    write_access_cases_csv,
    write_entries_csv,
    write_json,
)
from .models import CandidateRoute, RouteSeed
from .osm_poi import build_osm_poi_index
from .place_resolver import HybridPlaceResolver
from .route_research import merge_research_drafts, merge_route_optimizations
from .routes import generate_candidate_from_seed, load_route_seeds
from .service_pois import merge_verified_service_pois
from .validation import (
    OverpassClient,
    build_overpass_query,
    find_duplicate_routes,
    topology_failures,
    validate_amap_raw_evidence,
    validate_candidate,
)


EXPECTED_ROUTE_COUNT = 90
EXPECTED_MODE_COUNTS = {"walk": 30, "run": 30, "bike": 30}
DISTANCE_BANDS_M = {
    "walk": (("short", 1000, 2000), ("medium", 2000, 3500), ("long", 3500, 5000)),
    "run": (("short", 3000, 5000), ("medium", 5000, 10000), ("long", 10000, 15000)),
    "bike": (("short", 5000, 10000), ("medium", 10000, 20000), ("long", 20000, 30000)),
}


def _distance_band(route_mode: str, distance_m: int) -> str | None:
    bands = DISTANCE_BANDS_M.get(route_mode, ())
    for index, (name, lower, upper) in enumerate(bands):
        upper_included = index == len(bands) - 1
        if lower <= distance_m < upper or upper_included and distance_m == upper:
            return name
    return None


def _route_distribution(
    routes: list[CandidateRoute],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    mode_counts = {mode: 0 for mode in EXPECTED_MODE_COUNTS}
    band_counts = {
        mode: {"short": 0, "medium": 0, "long": 0} for mode in EXPECTED_MODE_COUNTS
    }
    for route in routes:
        if route.route_mode not in mode_counts:
            continue
        mode_counts[route.route_mode] += 1
        band = _distance_band(route.route_mode, route.actual_distance_m)
        if band is not None:
            band_counts[route.route_mode][band] += 1
    return mode_counts, band_counts


def main() -> None:
    parser = argparse.ArgumentParser(prog="xuhui-route-builder")
    parser.add_argument(
        "command",
        choices=[
            "merge-research",
            "merge-route-optimizations",
            "build-osm-poi-index",
            "resolve-seeds",
            "generate-routes",
            "validate-routes",
            "validate-seeds",
            "export-candidates",
            "merge-service-pois",
        ],
    )
    parser.add_argument("--max-online-calls", type=int, default=50)
    args = parser.parse_args()
    if args.command == "merge-research":
        merged = merge_research_drafts(
            PROJECT_ROOT / "data" / "seeds" / "research",
            PROJECT_ROOT / "data" / "seeds" / "route_seed_drafts.json",
            _validate_draft_collection,
        )
        print(f"merged_route_draft_count={len(merged)}")
    elif args.command == "merge-route-optimizations":
        target = PROJECT_ROOT / "data" / "seeds" / "route_seeds.json"
        merged = merge_route_optimizations(PROJECT_ROOT / "data" / "seeds" / "research", target, target)
        print(f"merged_route_optimization_count={len(merged)}")
    elif args.command == "build-osm-poi-index":
        settings = load_settings()
        client = OverpassClient(cache_dir=settings.raw_dir / "osm", timeout=180)
        pois = build_osm_poi_index(client, settings.interim_dir / "osm_poi_index.json")
        print(f"osm_poi_count={len(pois)}")
    elif args.command == "resolve-seeds":
        settings = load_settings()
        baidu_client = BaiduClient(settings.baidu_map_ak, settings.raw_dir / "baidu")
        resolver = HybridPlaceResolver(
            baidu_client,
            local_seed_path=settings.seed_dir / "route_seeds.json",
            osm_index_path=settings.interim_dir / "osm_poi_index.json",
            boundary_path=settings.web_data_dir / "xuhui_boundary.geojson",
            max_online_calls=args.max_online_calls,
        )
        seeds = resolve_seed_drafts(settings.project_root, resolver)
        print(f"resolved_route_seed_count={len(seeds)}")
        print(f"baidu_online_call_count={resolver.online_calls}")
    elif args.command == "generate-routes":
        settings = load_settings()
        client = AmapClient(settings.amap_web_service_key, settings.raw_dir / "amap")
        generate_routes(settings.project_root, client)
    elif args.command == "validate-routes":
        settings = load_settings()
        client = OverpassClient(cache_dir=settings.raw_dir / "osm")
        validate_routes(settings.project_root, client, datetime.now(timezone.utc))
    elif args.command == "validate-seeds":
        seeds = validate_seeds(PROJECT_ROOT)
        print(f"route_seed_count={len(seeds)}")
    elif args.command == "export-candidates":
        export_candidate_routes(PROJECT_ROOT)
    elif args.command == "merge-service-pois":
        merge_service_pois(PROJECT_ROOT)


def resolve_seed_drafts(project_root: Path, resolver) -> list[RouteSeed]:
    seed_dir = project_root / "data" / "seeds"
    draft_path = seed_dir / "route_seed_drafts.json"
    raw = json.loads(draft_path.read_text(encoding="utf-8"))
    _validate_draft_collection(raw)

    seeds: list[RouteSeed] = []
    resolution_failures: list[str] = []
    for draft_index, draft in enumerate(raw):
        nodes = draft.get("nodes")
        resolved_nodes = []
        raw_paths = []
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict) or not set(node).issubset(
                {"query", "expected_name", "expected_poi_id"}
            ):
                raise ValueError(
                    f"draft {draft.get('seed_id')} node {node_index} has invalid schema"
                )
            if not node.get("query") or not node.get("expected_name"):
                raise ValueError(
                    f"draft {draft.get('seed_id')} node {node_index} requires query and expected_name"
                )
            try:
                resolved, raw_path = resolver.resolve(
                    node["expected_name"],
                    node["query"],
                    node.get("expected_poi_id"),
                    str(draft.get("seed_id", "")),
                    node_index,
                )
            except Exception as exc:
                resolution_failures.append(
                    f"draft index={draft_index} seed_id={draft['seed_id']} node_index={node_index}: {exc}"
                )
                continue
            resolved_nodes.append(resolved)
            raw_paths.append(_portable_raw_path(project_root, raw_path))
        if len(resolved_nodes) != len(nodes):
            continue
        payload = {key: value for key, value in draft.items() if key != "nodes"}
        evidence = str(payload.get("evidence_note", "")).strip()
        payload["evidence_note"] = "；".join(
            [evidence, *(f"POI解析响应: {path}" for path in raw_paths)]
        )
        payload["ordered_nodes"] = resolved_nodes
        first_node, last_node = resolved_nodes[0], resolved_nodes[-1]
        same_endpoint = (
            first_node.node_name == last_node.node_name
            and first_node.lng_gcj02 == last_node.lng_gcj02
            and first_node.lat_gcj02 == last_node.lat_gcj02
        )
        payload["route_shape"] = "strict_loop" if same_endpoint else "one_way"
        payload["start_location"] = {
            "name": first_node.node_name,
            "location_type": "route_node",
            "lng_gcj02": first_node.lng_gcj02,
            "lat_gcj02": first_node.lat_gcj02,
            "source_url": payload["source_url"],
            "poi_id": first_node.poi_id,
        }
        payload["end_location"] = {
            "name": last_node.node_name,
            "location_type": "route_node",
            "lng_gcj02": last_node.lng_gcj02,
            "lat_gcj02": last_node.lat_gcj02,
            "source_url": payload["source_url"],
            "poi_id": last_node.poi_id,
        }
        payload["amenity_ids"] = []
        payload["geometry_action"] = "regenerate"
        try:
            seeds.append(RouteSeed(**payload))
        except Exception as exc:
            resolution_failures.append(
                f"draft index={draft_index} seed_id={draft['seed_id']}: {exc}"
            )

    if resolution_failures:
        raise ValueError(
            "route seed resolution failed:\n" + "\n".join(resolution_failures)
        )

    _validate_seed_collection(seeds)
    seed_dir.mkdir(parents=True, exist_ok=True)
    target = seed_dir / "route_seeds.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=seed_dir,
            prefix=".route_seeds.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(
                [seed.model_dump(mode="json") for seed in seeds],
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return seeds


def validate_seeds(project_root: Path) -> list[RouteSeed]:
    seeds = load_route_seeds(project_root / "data" / "seeds" / "route_seeds.json")
    _validate_seed_collection(seeds)
    return seeds


def generate_routes(project_root: Path, client) -> list:
    seeds = validate_seeds(project_root)
    candidates = []
    failures = []
    for index, seed in enumerate(seeds, start=1):
        try:
            candidate = generate_candidate_from_seed(seed, client, index)
            candidates.append(
                candidate.model_copy(
                    update={
                        "raw_response_paths": [
                            _portable_raw_path(project_root, path)
                            for path in candidate.raw_response_paths
                        ]
                    }
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "stage": "route_generation",
                    "seed_id": seed.seed_id,
                    "mode": seed.route_mode,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
    report = {
        "batch_status": "failed"
        if failures or len(candidates) != EXPECTED_ROUTE_COUNT
        else "preparing",
        "seed_count": len(seeds),
        "success_count": len(candidates),
        "failure_count": len(failures),
        "success_route_ids": [route.route_id for route in candidates],
        "failures": failures,
    }
    report_path = project_root / "data" / "processed" / "route_generation_report.json"
    candidate_path = project_root / "data" / "interim" / "pilot_candidates.json"
    _atomic_write_json(report_path, report)
    print(
        f"route_generation_success={len(candidates)} route_generation_failure={len(failures)}"
    )
    if failures or len(candidates) != EXPECTED_ROUTE_COUNT:
        raise RuntimeError(
            f"route generation batch failed: success={len(candidates)} failure={len(failures)}; "
            "existing pilot candidates preserved"
        )
    previous_candidate_exists = candidate_path.exists()
    previous_candidate_bytes = (
        candidate_path.read_bytes() if previous_candidate_exists else None
    )
    try:
        _atomic_write_json(
            candidate_path, [route.model_dump(mode="json") for route in candidates]
        )
    except Exception as exc:
        write_failure = {
            "stage": "candidate_write",
            "seed_id": None,
            "mode": None,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        report["batch_status"] = "failed"
        report["failure_count"] = 1
        report["failures"] = [write_failure]
        _atomic_write_json(report_path, report)
        raise RuntimeError(
            f"route generation batch failed while writing candidates: success={len(candidates)} failure=1; "
            "existing pilot candidates preserved"
        ) from exc
    report["batch_status"] = "succeeded"
    try:
        _atomic_write_json(report_path, report)
    except Exception as exc:
        rollback_error = None
        try:
            if previous_candidate_exists:
                _atomic_write_bytes(candidate_path, previous_candidate_bytes or b"")
            elif candidate_path.exists():
                candidate_path.unlink()
        except Exception as rollback_exc:
            rollback_error = rollback_exc
        detail = (
            f"; candidate rollback failed: {rollback_error}"
            if rollback_error is not None
            else ""
        )
        raise RuntimeError(
            f"route generation batch failed at report stage: success={len(candidates)} failure=1; "
            f"pilot candidates rolled back{detail}"
        ) from exc
    return candidates


def _portable_raw_path(project_root: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def validate_routes(
    project_root: Path, overpass_client, verified_at: datetime | None = None
) -> list[CandidateRoute]:
    verified_at = verified_at or datetime.now(timezone.utc)
    candidate_path = project_root / "data" / "interim" / "pilot_candidates.json"
    report_path = project_root / "data" / "processed" / "route_validation_report.json"
    try:
        raw = json.loads(candidate_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or len(raw) != EXPECTED_ROUTE_COUNT:
            raise ValueError(
                f"pilot candidates must contain exactly {EXPECTED_ROUTE_COUNT} routes"
            )
        candidates = [CandidateRoute.model_validate(item) for item in raw]
        if len({route.route_id for route in candidates}) != EXPECTED_ROUTE_COUNT:
            raise ValueError("pilot candidate route_id values must be unique")
        boundary_polygons = _load_boundary_polygons(
            project_root / "data" / "web" / "xuhui_boundary.geojson"
        )
    except Exception as exc:
        preflight_report = {
            "batch_status": "failed",
            "accepted_count": 0,
            "review_count": 0,
            "rejected_count": 0,
            "network_version": [],
            "duplicate_groups": {},
            "routes": [],
            "failures": [
                {
                    "stage": "candidate_preflight",
                    "candidate_path": str(candidate_path),
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            ],
        }
        _atomic_write_json(report_path, preflight_report)
        raise

    validated: list[CandidateRoute] = []
    failures: list[dict] = []
    network_versions: list[str] = []
    for route in candidates:
        try:
            shape_failures = topology_failures(route)
            if shape_failures:
                validated.append(
                    route.model_copy(
                        update={
                            "validation_status": "needs_review",
                            "verified_at": verified_at,
                            "review_note": f"本地形态门禁失败：{'；'.join(shape_failures)}",
                        }
                    )
                )
                continue
            evidence_failures = (
                validate_amap_raw_evidence(route, project_root)
                if route.geometry_source == "amap_direction"
                else []
            )
            payload = overpass_client.query(build_overpass_query(route))
            version = str(
                (payload.get("osm3s") or {}).get("timestamp_osm_base")
                or "overpass-version-unknown"
            )
            network_versions.append(version)
            validated.append(
                validate_candidate(
                    route,
                    payload,
                    verified_at,
                    version,
                    evidence_failures,
                    boundary_polygons,
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "route_id": route.route_id,
                    "mode": route.route_mode,
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            validated.append(
                CandidateRoute.model_validate(
                    {
                        **route.model_dump(),
                        "validation_status": "needs_review",
                        "verified_at": verified_at,
                        "review_note": f"Overpass 校验异常：{type(exc).__name__}: {exc}",
                    }
                )
            )

    accepted = [route for route in validated if route.validation_status == "accepted"]
    duplicate_groups = find_duplicate_routes(accepted)
    by_id = {route.route_id: route for route in validated}
    priority = {"A": 0, "B": 1, "C": 2}
    original_order = {route.route_id: index for index, route in enumerate(validated)}
    for leader_id, duplicate_ids in duplicate_groups.items():
        group_ids = [leader_id, *duplicate_ids]
        keep_id = min(
            group_ids,
            key=lambda route_id: (
                priority[by_id[route_id].source_level],
                original_order[route_id],
            ),
        )
        for route_id in group_ids:
            if route_id == keep_id:
                continue
            route = by_id[route_id]
            replacement = CandidateRoute.model_validate(
                {
                    **route.model_dump(),
                    "validation_status": "needs_review",
                    "review_note": f"与路线 {keep_id} 几何重复；按来源等级和原始顺序保留 {keep_id}",
                }
            )
            by_id[route_id] = replacement
            validated[original_order[route_id]] = replacement

    counts = {
        "accepted_count": sum(
            route.validation_status == "accepted" for route in validated
        ),
        "review_count": sum(
            route.validation_status == "needs_review" for route in validated
        ),
        "rejected_count": sum(
            route.validation_status == "rejected" for route in validated
        ),
    }
    publishable = [route for route in validated if route.is_publishable()]
    mode_counts, distance_band_counts = _route_distribution(validated)
    collection_valid = len(validated) == EXPECTED_ROUTE_COUNT and mode_counts == EXPECTED_MODE_COUNTS
    distinct_versions = list(dict.fromkeys(network_versions))
    report = {
        "batch_status": "preparing" if collection_valid else "failed",
        **counts,
        "published_count": len(publishable) if collection_valid else 0,
        "mode_counts": mode_counts,
        "distance_band_counts": distance_band_counts,
        "network_version": distinct_versions[0]
        if len(distinct_versions) == 1
        else distinct_versions,
        "duplicate_groups": duplicate_groups,
        "routes": [
            {
                "route_id": route.route_id,
                "mode": route.route_mode,
                "validation_status": route.validation_status,
                "snap_ratio": route.snap_ratio,
                "route_inside_ratio": route.route_inside_ratio,
                "source_accessed_at": route.source_accessed_at.isoformat()
                if route.source_accessed_at
                else None,
                "network_source": route.network_source,
                "review_note": route.review_note,
            }
            for route in validated
        ],
        "failures": failures,
    }
    processed = project_root / "data" / "processed"
    validated_path = processed / "pilot_validated.json"
    _atomic_write_json(
        validated_path, [route.model_dump(mode="json") for route in validated]
    )

    if not collection_valid:
        _atomic_write_json(report_path, report)
        raise RuntimeError(
            "route validation failed: "
            f"accepted={counts['accepted_count']} review={counts['review_count']} rejected={counts['rejected_count']}; "
            f"mode_counts={mode_counts} distance_band_counts={distance_band_counts}; "
            "existing web files preserved"
        )

    web = project_root / "data" / "web"
    web_targets = [web / "xuhui_routes.geojson", web / "route_catalog.json"]
    web_snapshots = _snapshot_files(web_targets)
    _atomic_write_json(report_path, report)
    try:
        _write_json_transaction(
            web_targets,
            [
                build_route_feature_collection(publishable),
                build_route_catalog(publishable),
            ],
        )
    except Exception as exc:
        cause = exc.__cause__ or exc
        report["batch_status"] = "failed"
        report["failures"].append(_stage_failure("web_publish", cause))
        _atomic_write_json(report_path, report)
        raise

    report["batch_status"] = "succeeded" if len(publishable) == EXPECTED_ROUTE_COUNT else "partial"
    try:
        _atomic_write_json(report_path, report)
    except Exception as exc:
        _restore_files(web_targets, web_snapshots)
        report["batch_status"] = "failed"
        report["failures"].append(_stage_failure("success_report", exc))
        try:
            _atomic_write_json(report_path, report)
        except Exception:
            pass
        raise RuntimeError(
            "success report write failed; web files rolled back"
        ) from exc
    return validated


def _load_boundary_polygons(path: Path) -> list[list[list[float]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    polygons: list[list[list[float]]] = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") == "Polygon" and coordinates:
            polygons.append(coordinates[0])
        elif geometry.get("type") == "MultiPolygon":
            polygons.extend(polygon[0] for polygon in coordinates if polygon)
    if not polygons:
        raise ValueError(f"Xuhui boundary contains no polygons: {path}")
    return polygons


def _write_json_transaction(targets: list[Path], payloads: list) -> None:
    snapshots = _snapshot_files(targets)
    try:
        for path, payload in zip(targets, payloads):
            _atomic_write_json(path, payload)
    except Exception as exc:
        rollback_failures = _restore_files(targets, snapshots)
        detail = f"; rollback failures={rollback_failures}" if rollback_failures else ""
        raise RuntimeError(
            f"publish transaction failed; all targets rolled back{detail}"
        ) from exc


def _snapshot_files(targets: list[Path]) -> list[tuple[bool, bytes]]:
    return [
        (path.exists(), path.read_bytes() if path.exists() else b"") for path in targets
    ]


def _restore_files(
    targets: list[Path], snapshots: list[tuple[bool, bytes]]
) -> list[str]:
    failures = []
    for path, (existed, content) in zip(targets, snapshots):
        try:
            if existed:
                _atomic_write_bytes(path, content)
            elif path.exists():
                path.unlink()
        except Exception as exc:
            failures.append(f"{path}: {exc}")
    return failures


def _stage_failure(stage: str, exc: Exception) -> dict:
    return {
        "stage": stage,
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
    }


def _atomic_write_json(target: Path, payload) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _validate_seed_collection(seeds: list[RouteSeed]) -> None:
    if len(seeds) != EXPECTED_ROUTE_COUNT:
        raise ValueError(
            f"route seeds must contain exactly {EXPECTED_ROUTE_COUNT} routes"
        )
    counts = {
        mode: sum(seed.route_mode == mode for seed in seeds)
        for mode in ("run", "walk", "bike")
    }
    if counts != {"run": 30, "walk": 30, "bike": 30}:
        raise ValueError(f"route mode counts must be 30 each: {counts}")
    if len({seed.seed_id for seed in seeds}) != len(seeds):
        raise ValueError("route seed_id values must be unique")
    if len({seed.route_name for seed in seeds}) != len(seeds):
        raise ValueError("route_name values must be unique")
    for seed in seeds:
        if (
            not seed.source_name.strip()
            or not seed.source_url.strip()
            or not seed.evidence_note.strip()
        ):
            raise ValueError(f"seed {seed.seed_id} requires source evidence")
        if not seed.access_restrictions:
            raise ValueError(f"seed {seed.seed_id} requires access restrictions")
        for node in seed.ordered_nodes:
            if node.lng_gcj02 is None or node.lat_gcj02 is None:
                raise ValueError(f"seed {seed.seed_id} contains unresolved nodes")


def _validate_draft_collection(raw) -> None:
    if not isinstance(raw, list):
        raise ValueError(
            "draft index=collection seed_id=<unknown>: drafts must be a list"
        )
    if len(raw) != EXPECTED_ROUTE_COUNT:
        raise ValueError(
            f"draft index=collection seed_id=<unknown>: expected {EXPECTED_ROUTE_COUNT} drafts, got {len(raw)}"
        )
    allowed_keys = {
        "seed_id",
        "route_name",
        "route_mode",
        "distance_level",
        "target_distance_m",
        "region_zone",
        "start_hint",
        "end_hint",
        "waypoint_hints",
        "tags",
        "reason",
        "source_name",
        "source_url",
        "source_accessed_at",
        "confidence",
        "source_level",
        "evidence_note",
        "access_restrictions",
        "allowed_modes",
        "nodes",
    }
    required_text = {
        "seed_id",
        "route_name",
        "source_name",
        "source_url",
        "source_accessed_at",
        "reason",
        "evidence_note",
    }
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    counts = {"run": 0, "walk": 0, "bike": 0}
    band_counts = {mode: {"short": 0, "medium": 0, "long": 0} for mode in counts}
    for draft_index, draft in enumerate(raw):
        seed_id = (
            str(draft.get("seed_id", "")) if isinstance(draft, dict) else "<unknown>"
        )
        context = f"draft index={draft_index} seed_id={seed_id or '<unknown>'}"
        if not isinstance(draft, dict):
            raise ValueError(f"{context}: item must be a dict")
        extras = set(draft) - allowed_keys
        missing = allowed_keys - set(draft)
        if extras or missing:
            raise ValueError(
                f"{context}: extra or missing fields: extra={sorted(extras)} missing={sorted(missing)}"
            )
        for field in required_text:
            if not isinstance(draft[field], str) or not draft[field].strip():
                raise ValueError(f"{context}: {field} must be non-empty")
        if draft["seed_id"] in seen_ids:
            raise ValueError(f"{context}: seed_id must be unique")
        if draft["route_name"] in seen_names:
            raise ValueError(f"{context}: route_name must be unique")
        seen_ids.add(draft["seed_id"])
        seen_names.add(draft["route_name"])
        mode = draft["route_mode"]
        if mode not in counts:
            raise ValueError(f"{context}: route_mode must be run, walk, or bike")
        counts[mode] += 1
        band = _distance_band(mode, draft["target_distance_m"])
        if band is None:
            raise ValueError(
                f"{context}: target_distance_m falls outside the approved range"
            )
        band_counts[mode][band] += 1
        if draft["source_level"] not in {"A", "B", "C"}:
            raise ValueError(f"{context}: source_level must be A, B, or C")
        if not str(draft["source_url"]).startswith("https://"):
            raise ValueError(f"{context}: source_url must use https")
        try:
            date.fromisoformat(draft["source_accessed_at"])
        except ValueError as exc:
            raise ValueError(
                f"{context}: source_accessed_at must use YYYY-MM-DD"
            ) from exc
        if (
            not isinstance(draft["access_restrictions"], list)
            or not draft["access_restrictions"]
            or not all(str(item).strip() for item in draft["access_restrictions"])
        ):
            raise ValueError(f"{context}: access_restrictions must be non-empty")
        if (
            not isinstance(draft["allowed_modes"], list)
            or mode not in draft["allowed_modes"]
        ):
            raise ValueError(f"{context}: allowed_modes must contain route_mode")
        nodes = draft["nodes"]
        if not isinstance(nodes, list) or len(nodes) < 2:
            raise ValueError(f"{context}: nodes must contain at least two items")
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict) or not set(node).issubset(
                {"query", "expected_name", "expected_poi_id"}
            ):
                raise ValueError(
                    f"{context}: nodes[{node_index}] has extra or invalid fields"
                )
            if not node.get("query") or not node.get("expected_name"):
                raise ValueError(
                    f"{context}: nodes[{node_index}] requires query and expected_name"
                )
    if counts != {"run": 30, "walk": 30, "bike": 30}:
        raise ValueError(
            f"draft index=collection seed_id=<unknown>: route mode counts must be 30 each: {counts}"
        )
    if not all(
        count == {"short": 10, "medium": 10, "long": 10}
        for count in band_counts.values()
    ):
        raise ValueError(
            f"draft index=collection seed_id=<unknown>: distance bands must contain 10 routes each: {band_counts}"
        )


def _route_distribution_from_targets(
    seeds: list[RouteSeed],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    mode_counts = {mode: 0 for mode in EXPECTED_MODE_COUNTS}
    band_counts = {mode: {"short": 0, "medium": 0, "long": 0} for mode in EXPECTED_MODE_COUNTS}
    for seed in seeds:
        mode_counts[seed.route_mode] += 1
        band = _distance_band(seed.route_mode, seed.target_distance_m)
        if band is not None:
            band_counts[seed.route_mode][band] += 1
    return mode_counts, band_counts


def export_candidate_routes(project_root: Path) -> list[CandidateRoute]:
    source = project_root / "data" / "processed" / "pilot_validated.json"
    routes = [
        CandidateRoute.model_validate(item)
        for item in json.loads(source.read_text(encoding="utf-8"))
    ]
    if (
        len(routes) != EXPECTED_ROUTE_COUNT
        or len({route.route_id for route in routes}) != EXPECTED_ROUTE_COUNT
    ):
        raise ValueError("candidate web export requires 90 unique routes")
    counts = {
        mode: sum(route.route_mode == mode for route in routes)
        for mode in EXPECTED_MODE_COUNTS
    }
    if counts != EXPECTED_MODE_COUNTS:
        raise ValueError(f"candidate web export requires 30 routes per mode: {counts}")
    if any(
        route.validation_status not in {"accepted", "needs_review"} for route in routes
    ):
        raise ValueError(
            "candidate web export only accepts accepted or needs_review routes"
        )

    web = project_root / "data" / "web"
    _atomic_write_json(
        web / "xuhui_routes.geojson", build_candidate_route_feature_collection(routes)
    )
    _atomic_write_json(
        web / "route_catalog.json", build_candidate_route_catalog(routes)
    )
    print(
        f"candidate_web_routes={len(routes)} "
        f"accepted={sum(route.validation_status == 'accepted' for route in routes)} "
        f"needs_review={sum(route.validation_status == 'needs_review' for route in routes)}"
    )
    return routes


def merge_service_pois(project_root: Path) -> list[CandidateRoute]:
    processed = project_root / "data" / "processed"
    route_path = processed / "pilot_validated.json"
    routes = [
        CandidateRoute.model_validate(item)
        for item in json.loads(route_path.read_text(encoding="utf-8"))
    ]
    poi_dir = project_root / "data" / "interim" / "poi"
    source_paths = [
        poi_dir / "walk_route_pois.json",
        poi_dir / "run_route_pois.json",
        poi_dir / "bike_route_pois.json",
    ]
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in source_paths]
    updated, poi_catalog, report = merge_verified_service_pois(routes, documents)
    publishable = [route for route in updated if route.is_publishable()]
    web = project_root / "data" / "web"
    _atomic_write_json(route_path, [route.model_dump(mode="json") for route in updated])
    _write_json_transaction(
        [web / "xuhui_routes.geojson", web / "route_catalog.json", web / "poi_catalog.json"],
        [
            build_route_feature_collection(publishable),
            build_route_catalog(publishable),
            poi_catalog,
        ],
    )
    report["published_route_count"] = len(publishable)
    report["source_files"] = [path.relative_to(project_root).as_posix() for path in source_paths]
    _atomic_write_json(processed / "poi_merge_report.json", report)
    print(
        f"published_route_count={len(publishable)} "
        f"published_poi_count={report['published_unique_poi_count']} "
        f"published_association_count={report['published_association_count']}"
    )
    return updated


def export_demo(project_root: Path) -> None:
    dataset = build_demo_dataset()
    web_dir = project_root / "data" / "web"
    write_json(
        web_dir / "xuhui_boundary.geojson",
        {"type": "FeatureCollection", "features": [dataset.boundary]},
    )
    write_json(
        web_dir / "xuhui_entries.geojson", build_feature_collection(dataset.entries)
    )
    write_json(
        web_dir / "xuhui_routes.geojson", build_route_feature_collection(dataset.routes)
    )
    write_json(web_dir / "route_catalog.json", build_route_catalog(dataset.routes))
    write_json(web_dir / "poi_catalog.json", build_poi_feature_collection(dataset.pois))
    write_json(
        web_dir / "access_cases.json", build_access_catalog(dataset.access_cases)
    )
    write_entries_csv(
        project_root / "data" / "processed" / "xuhui_entry_pool.csv", dataset.entries
    )
    write_access_cases_csv(
        project_root / "data" / "processed" / "xuhui_access_cases.csv",
        dataset.access_cases,
    )
    print(
        " ".join(
            [
                f"exported_entries={len(dataset.entries)}",
                f"exported_routes={len(dataset.routes)}",
                f"exported_pois={len(dataset.pois)}",
                f"exported_access_cases={len(dataset.access_cases)}",
            ]
        )
    )


if __name__ == "__main__":
    main()
