from __future__ import annotations

import argparse
import json
import os
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .amap_client import AmapClient
from .config import PROJECT_ROOT, load_settings
from .demo_dataset import build_demo_dataset
from .exporters import (
    build_access_catalog,
    build_feature_collection,
    build_poi_feature_collection,
    build_route_catalog,
    build_route_feature_collection,
    write_access_cases_csv,
    write_entries_csv,
    write_json,
)
from .models import CandidateRoute, RouteSeed
from .routes import generate_candidate_from_seed, load_route_seeds, resolve_node_query
from .validation import (
    OverpassClient,
    build_overpass_query,
    find_duplicate_routes,
    validate_amap_raw_evidence,
    validate_candidate,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="xuhui-route-builder")
    parser.add_argument("command", choices=["resolve-seeds", "generate-routes", "validate-routes", "validate-seeds"])
    args = parser.parse_args()
    if args.command == "resolve-seeds":
        settings = load_settings()
        client = AmapClient(settings.amap_web_service_key, settings.raw_dir / "amap")
        seeds = resolve_seed_drafts(settings.project_root, client)
        print(f"resolved_route_seed_count={len(seeds)}")
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


def resolve_seed_drafts(project_root: Path, client) -> list[RouteSeed]:
    seed_dir = project_root / "data" / "seeds"
    draft_path = seed_dir / "route_seed_drafts.json"
    raw = json.loads(draft_path.read_text(encoding="utf-8"))
    _validate_draft_collection(raw)

    seeds: list[RouteSeed] = []
    for draft_index, draft in enumerate(raw):
        nodes = draft.get("nodes")
        resolved_nodes = []
        raw_paths = []
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict) or not set(node).issubset({"query", "expected_name", "expected_poi_id"}):
                raise ValueError(f"draft {draft.get('seed_id')} node {node_index} has invalid schema")
            if not node.get("query") or not node.get("expected_name"):
                raise ValueError(f"draft {draft.get('seed_id')} node {node_index} requires query and expected_name")
            try:
                resolved, raw_path = resolve_node_query(
                    node["expected_name"],
                    node["query"],
                    client,
                    node.get("expected_poi_id"),
                    str(draft.get("seed_id", "")),
                    node_index,
                )
            except Exception as exc:
                raise ValueError(f"draft index={draft_index} seed_id={draft['seed_id']} node_index={node_index}: {exc}") from exc
            resolved_nodes.append(resolved)
            raw_paths.append(_portable_raw_path(project_root, raw_path))
        payload = {key: value for key, value in draft.items() if key != "nodes"}
        evidence = str(payload.get("evidence_note", "")).strip()
        payload["evidence_note"] = "；".join([evidence, *(f"POI解析响应: {path}" for path in raw_paths)])
        payload["ordered_nodes"] = resolved_nodes
        try:
            seeds.append(RouteSeed(**payload))
        except Exception as exc:
            raise ValueError(f"draft index={draft_index} seed_id={draft['seed_id']}: {exc}") from exc

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
            json.dump([seed.model_dump(mode="json") for seed in seeds], handle, ensure_ascii=False, indent=2)
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
            candidates.append(candidate.model_copy(update={
                "raw_response_paths": [
                    _portable_raw_path(project_root, path) for path in candidate.raw_response_paths
                ]
            }))
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
        "batch_status": "failed" if failures or len(candidates) != 15 else "preparing",
        "seed_count": len(seeds),
        "success_count": len(candidates),
        "failure_count": len(failures),
        "success_route_ids": [route.route_id for route in candidates],
        "failures": failures,
    }
    report_path = project_root / "data" / "processed" / "route_generation_report.json"
    candidate_path = project_root / "data" / "interim" / "pilot_candidates.json"
    _atomic_write_json(report_path, report)
    print(f"route_generation_success={len(candidates)} route_generation_failure={len(failures)}")
    if failures or len(candidates) != 15:
        raise RuntimeError(
            f"route generation batch failed: success={len(candidates)} failure={len(failures)}; "
            "existing pilot candidates preserved"
        )
    previous_candidate_exists = candidate_path.exists()
    previous_candidate_bytes = candidate_path.read_bytes() if previous_candidate_exists else None
    try:
        _atomic_write_json(candidate_path, [route.model_dump(mode="json") for route in candidates])
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
        detail = f"; candidate rollback failed: {rollback_error}" if rollback_error is not None else ""
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


def validate_routes(project_root: Path, overpass_client, verified_at: datetime | None = None) -> list[CandidateRoute]:
    verified_at = verified_at or datetime.now(timezone.utc)
    candidate_path = project_root / "data" / "interim" / "pilot_candidates.json"
    report_path = project_root / "data" / "processed" / "route_validation_report.json"
    try:
        raw = json.loads(candidate_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or len(raw) != 15:
            raise ValueError("pilot candidates must contain exactly 15 routes")
        candidates = [CandidateRoute.model_validate(item) for item in raw]
        if len({route.route_id for route in candidates}) != 15:
            raise ValueError("pilot candidate route_id values must be unique")
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
            evidence_failures = validate_amap_raw_evidence(route, project_root)
            payload = overpass_client.query(build_overpass_query(route))
            version = str((payload.get("osm3s") or {}).get("timestamp_osm_base") or "overpass-version-unknown")
            network_versions.append(version)
            validated.append(validate_candidate(route, payload, verified_at, version, evidence_failures))
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
        keep_id = min(group_ids, key=lambda route_id: (priority[by_id[route_id].source_level], original_order[route_id]))
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
        "accepted_count": sum(route.validation_status == "accepted" for route in validated),
        "review_count": sum(route.validation_status == "needs_review" for route in validated),
        "rejected_count": sum(route.validation_status == "rejected" for route in validated),
    }
    publishable = [route for route in validated if route.is_publishable()]
    distinct_versions = list(dict.fromkeys(network_versions))
    report = {
        "batch_status": "preparing" if publishable else "failed",
        **counts,
        "published_count": len(publishable),
        "network_version": distinct_versions[0] if len(distinct_versions) == 1 else distinct_versions,
        "duplicate_groups": duplicate_groups,
        "routes": [
            {
                "route_id": route.route_id,
                "mode": route.route_mode,
                "validation_status": route.validation_status,
                "snap_ratio": route.snap_ratio,
                "network_source": route.network_source,
                "review_note": route.review_note,
            }
            for route in validated
        ],
        "failures": failures,
    }
    processed = project_root / "data" / "processed"
    validated_path = processed / "pilot_validated.json"
    _atomic_write_json(validated_path, [route.model_dump(mode="json") for route in validated])

    if not publishable:
        _atomic_write_json(report_path, report)
        raise RuntimeError(
            "route validation failed: "
            f"accepted={counts['accepted_count']} review={counts['review_count']} rejected={counts['rejected_count']}; "
            "no network-matched routes available; existing web files preserved"
        )

    web = project_root / "data" / "web"
    web_targets = [web / "xuhui_routes.geojson", web / "route_catalog.json"]
    web_snapshots = _snapshot_files(web_targets)
    _atomic_write_json(report_path, report)
    try:
        _write_json_transaction(
            web_targets,
            [build_route_feature_collection(publishable), build_route_catalog(publishable)],
        )
    except Exception as exc:
        cause = exc.__cause__ or exc
        report["batch_status"] = "failed"
        report["failures"].append(_stage_failure("web_publish", cause))
        _atomic_write_json(report_path, report)
        raise

    report["batch_status"] = "succeeded" if len(publishable) == len(validated) else "partial"
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
        raise RuntimeError("success report write failed; web files rolled back") from exc
    return validated


def _write_json_transaction(targets: list[Path], payloads: list) -> None:
    snapshots = _snapshot_files(targets)
    try:
        for path, payload in zip(targets, payloads):
            _atomic_write_json(path, payload)
    except Exception as exc:
        rollback_failures = _restore_files(targets, snapshots)
        detail = f"; rollback failures={rollback_failures}" if rollback_failures else ""
        raise RuntimeError(f"publish transaction failed; all targets rolled back{detail}") from exc


def _snapshot_files(targets: list[Path]) -> list[tuple[bool, bytes]]:
    return [(path.exists(), path.read_bytes() if path.exists() else b"") for path in targets]


def _restore_files(targets: list[Path], snapshots: list[tuple[bool, bytes]]) -> list[str]:
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
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def _atomic_write_json(target: Path, payload) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp", delete=False
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
            mode="wb", dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp", delete=False
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
    if len(seeds) != 15:
        raise ValueError("route seeds must contain exactly 15 routes")
    counts = {mode: sum(seed.route_mode == mode for seed in seeds) for mode in ("run", "walk", "bike")}
    if counts != {"run": 5, "walk": 5, "bike": 5}:
        raise ValueError(f"route mode counts must be 5 each: {counts}")
    if len({seed.seed_id for seed in seeds}) != len(seeds):
        raise ValueError("route seed_id values must be unique")
    if len({seed.route_name for seed in seeds}) != len(seeds):
        raise ValueError("route_name values must be unique")
    for seed in seeds:
        if not seed.source_name.strip() or not seed.source_url.strip() or not seed.evidence_note.strip():
            raise ValueError(f"seed {seed.seed_id} requires source evidence")
        if not seed.access_restrictions:
            raise ValueError(f"seed {seed.seed_id} requires access restrictions")
        for node in seed.ordered_nodes:
            if not node.poi_id or node.lng_gcj02 is None or node.lat_gcj02 is None:
                raise ValueError(f"seed {seed.seed_id} contains unresolved nodes")


def _validate_draft_collection(raw) -> None:
    if not isinstance(raw, list):
        raise ValueError("draft index=collection seed_id=<unknown>: drafts must be a list")
    if len(raw) != 15:
        raise ValueError(f"draft index=collection seed_id=<unknown>: expected 15 drafts, got {len(raw)}")
    allowed_keys = {
        "seed_id", "route_name", "route_mode", "distance_level", "target_distance_m", "region_zone",
        "start_hint", "end_hint", "waypoint_hints", "tags", "reason", "source_name", "source_url",
        "confidence", "source_level", "evidence_note", "access_restrictions", "allowed_modes", "nodes",
    }
    required_text = {"seed_id", "route_name", "source_name", "source_url", "reason", "evidence_note"}
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    counts = {"run": 0, "walk": 0, "bike": 0}
    for draft_index, draft in enumerate(raw):
        seed_id = str(draft.get("seed_id", "")) if isinstance(draft, dict) else "<unknown>"
        context = f"draft index={draft_index} seed_id={seed_id or '<unknown>'}"
        if not isinstance(draft, dict):
            raise ValueError(f"{context}: item must be a dict")
        extras = set(draft) - allowed_keys
        missing = allowed_keys - set(draft)
        if extras or missing:
            raise ValueError(f"{context}: extra or missing fields: extra={sorted(extras)} missing={sorted(missing)}")
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
        if draft["source_level"] not in {"A", "B", "C"}:
            raise ValueError(f"{context}: source_level must be A, B, or C")
        if not str(draft["source_url"]).startswith("https://"):
            raise ValueError(f"{context}: source_url must use https")
        if not isinstance(draft["access_restrictions"], list) or not draft["access_restrictions"] or not all(str(item).strip() for item in draft["access_restrictions"]):
            raise ValueError(f"{context}: access_restrictions must be non-empty")
        if not isinstance(draft["allowed_modes"], list) or mode not in draft["allowed_modes"]:
            raise ValueError(f"{context}: allowed_modes must contain route_mode")
        nodes = draft["nodes"]
        if not isinstance(nodes, list) or len(nodes) < 2:
            raise ValueError(f"{context}: nodes must contain at least two items")
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict) or not set(node).issubset({"query", "expected_name", "expected_poi_id"}):
                raise ValueError(f"{context}: nodes[{node_index}] has extra or invalid fields")
            if not node.get("query") or not node.get("expected_name"):
                raise ValueError(f"{context}: nodes[{node_index}] requires query and expected_name")
    if counts != {"run": 5, "walk": 5, "bike": 5}:
        raise ValueError(f"draft index=collection seed_id=<unknown>: route mode counts must be 5 each: {counts}")


def export_demo(project_root: Path) -> None:
    dataset = build_demo_dataset()
    web_dir = project_root / "data" / "web"
    write_json(web_dir / "xuhui_boundary.geojson", {"type": "FeatureCollection", "features": [dataset.boundary]})
    write_json(web_dir / "xuhui_entries.geojson", build_feature_collection(dataset.entries))
    write_json(web_dir / "xuhui_routes.geojson", build_route_feature_collection(dataset.routes))
    write_json(web_dir / "route_catalog.json", build_route_catalog(dataset.routes))
    write_json(web_dir / "poi_catalog.json", build_poi_feature_collection(dataset.pois))
    write_json(web_dir / "access_cases.json", build_access_catalog(dataset.access_cases))
    write_entries_csv(project_root / "data" / "processed" / "xuhui_entry_pool.csv", dataset.entries)
    write_access_cases_csv(project_root / "data" / "processed" / "xuhui_access_cases.csv", dataset.access_cases)
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
