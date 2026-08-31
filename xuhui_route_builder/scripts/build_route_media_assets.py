from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_CATALOG = REPO_ROOT / "data" / "web" / "route_catalog.json"
MANIFEST_PATH = REPO_ROOT / "data" / "web" / "route_media_manifest.json"
REGISTRY_PATH = REPO_ROOT / "data" / "seeds" / "route_photo_registry.json"
OUTPUT_DIR = REPO_ROOT / "web" / "assets" / "routes"
CUTOFF = date(2016, 8, 31)
SLOTS = ("cover", "context", "detail")
MAX_TOTAL_REUSE = 4
MAX_COVER_REUSE = 2
MAX_UNIQUE_ASSETS = 180
ROUTE_SLOT_OVERRIDES = {
    "XH_WALK_0007": {
        "cover": "XH_IMG_XHS_69676538000000001A035E41_03",
        "detail": "XH_IMG_XHS_66C750C4000000001D016439_07",
    }
}

EXCLUDED_EXISTING_ASSETS = {
    "XH_IMG_GARDEN_003",
    "XH_IMG_GARDEN_004",
    "XH_IMG_GARDEN_005",
    "XH_IMG_HENGFU_001",
    "XH_IMG_HENGFU_009",
    "XH_IMG_LONGHUA_003",
    "XH_IMG_LONGHUA_009",
}
PURE_SCENERY_EXISTING_ASSETS = {"XH_IMG_KANGJIAN_002"}
EXISTING_AREA_BY_TOKEN = {
    "WESTBUND": ["west_bund"],
    "LONGHUA": ["longhua"],
    "HUAJING": ["huajing"],
    "XJH": ["xujiahui"],
    "HENGFU": ["hengfu"],
    "GARDEN": ["shanghai_botanical_garden"],
    "CAOHEJING": ["caohejing"],
    "KANGJIAN": ["kangjian"],
    "NANZHAN": ["shanghai_botanical_garden", "huajing"],
    "COMMONS": ["hengfu"],
}
AREA_ALIASES = {
    "west_bund": "west_bund",
    "西岸": "west_bund",
    "徐汇滨江": "west_bund",
    "longhua": "longhua",
    "龙华": "longhua",
    "huajing": "huajing",
    "华泾": "huajing",
    "xujiahui": "xujiahui",
    "xujiahui_sports": "xujiahui",
    "徐家汇": "xujiahui",
    "hengfu": "hengfu",
    "衡复": "hengfu",
    "shanghai_botanical_garden": "shanghai_botanical_garden",
    "botanical_garden": "shanghai_botanical_garden",
    "garden": "shanghai_botanical_garden",
    "上海植物园": "shanghai_botanical_garden",
    "植物园": "shanghai_botanical_garden",
    "caohejing": "caohejing",
    "漕河泾": "caohejing",
    "kangjian": "kangjian",
    "康健": "kangjian",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建徐汇90条路线的完整图片清单")
    parser.add_argument(
        "--import-root",
        action="append",
        default=[],
        type=Path,
        help="包含 candidates.json 与 images/ 的审核素材目录，可重复传入",
    )
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_captured_at(value: str) -> tuple[str, date]:
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        captured = date(int(text), 1, 1)
        return text, captured
    normalized = text.replace("Z", "+00:00").replace(" ", "T")
    try:
        captured = datetime.fromisoformat(normalized).date()
    except ValueError:
        captured = date.fromisoformat(text[:10])
    return captured.isoformat(), captured


def normalize_areas(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(item).strip() for item in value]
    else:
        raw_items = [item.strip() for item in re.split(r"[,，/、;；]", str(value))]
    normalized: list[str] = []
    for item in raw_items:
        if not item:
            continue
        direct = AREA_ALIASES.get(item)
        if direct and direct not in normalized:
            normalized.append(direct)
            continue
        for alias, area_id in AREA_ALIASES.items():
            if alias in item and area_id not in normalized:
                normalized.append(area_id)
    if any(
        token in str(value)
        for token in ("上海南站", "南站", "nanzhan", "south_station")
    ):
        for area_id in ("shanghai_botanical_garden", "huajing"):
            if area_id not in normalized:
                normalized.append(area_id)
    return normalized


def normalize_slots(value: Any) -> list[str]:
    if not isinstance(value, list):
        value = re.split(r"[,，/、;；]", str(value or ""))
    slot_aliases = {
        "cover": "cover",
        "封面": "cover",
        "主图": "cover",
        "路线卡片": "cover",
        "overview": "cover",
        "context": "context",
        "环境": "context",
        "沿线实景": "context",
        "waypoint_background": "context",
        "detail": "detail",
        "细节": "detail",
        "详情页": "detail",
    }
    slots: list[str] = []
    for item in value:
        text = str(item).strip()
        for alias, slot in slot_aliases.items():
            if alias in text and slot not in slots:
                slots.append(slot)
    return slots


def normalize_asset_id(value: str, source_sha256: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").upper()
    if not stem:
        stem = f"XH_IMG_IMPORTED_{source_sha256[:10].upper()}"
    if not stem.startswith("XH_IMG_"):
        stem = f"XH_IMG_{stem}"
    return stem


def existing_areas(asset_id: str) -> list[str]:
    for token, area_ids in EXISTING_AREA_BY_TOKEN.items():
        if token in asset_id:
            return area_ids
    raise ValueError(f"旧素材缺少区域映射: {asset_id}")


def seed_from_current_manifest() -> list[dict[str, Any]]:
    if not MANIFEST_PATH.is_file():
        return []
    manifest = load_json(MANIFEST_PATH)
    assets: list[dict[str, Any]] = []
    for asset_id, source in sorted(manifest["assets"].items()):
        if asset_id in EXCLUDED_EXISTING_ASSETS:
            continue
        captured_at, captured_date = parse_captured_at(source["captured_at"])
        if captured_date < CUTOFF:
            continue
        path = REPO_ROOT / "web" / source["src"].removeprefix("./")
        if not path.is_file():
            raise FileNotFoundError(path)
        assets.append(
            {
                "asset_id": asset_id,
                "source_platform": "existing_curated_source",
                "source_page_url": source["source_page_url"],
                "source_post_id": None,
                "source_image_index": None,
                "author": source.get("author") or "来源页作者",
                "captured_at": captured_at,
                "date_basis": "source_metadata",
                "accessed_at": date.today().isoformat(),
                "scene_area_ids": existing_areas(asset_id),
                "scene_name": source["scene_name"],
                "road_visible": asset_id not in PURE_SCENERY_EXISTING_ASSETS,
                "route_ids": [],
                "slot_recommendations": ["cover", "context", "detail"],
                "quality_status": "accepted",
                "usage_scope": "competition_demo_only",
                "source_file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "source_sha256": source["original_sha256"],
                "notes": "上一轮已人工核验，已排除早于日期下限的素材",
            }
        )
    return assets


def load_registry() -> list[dict[str, Any]]:
    if REGISTRY_PATH.is_file():
        return load_json(REGISTRY_PATH)["assets"]
    return seed_from_current_manifest()


def candidate_records(root: Path) -> list[dict[str, Any]]:
    path = root / "candidates.json"
    payload = load_json(path)
    if isinstance(payload, dict):
        payload = payload.get("candidates", payload.get("assets", []))
    if not isinstance(payload, list):
        raise TypeError(f"候选表需要是数组: {path}")
    return payload


def resolve_candidate_path(root: Path, record: dict[str, Any]) -> Path:
    raw_path = Path(str(record["file_path"]))
    candidates = [raw_path] if raw_path.is_absolute() else [root / raw_path]
    candidates.append(root / "images" / raw_path.name)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f"候选图片不存在: {record['file_path']}")


def inspect_source(path: Path) -> tuple[str, list[int]]:
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        dimensions = list(image.size)
        image.verify()
    if min(dimensions) < 720:
        raise ValueError(f"候选图片短边低于720像素: {path} {dimensions}")
    return source_sha256, dimensions


def import_candidates(
    current_assets: list[dict[str, Any]], roots: list[Path]
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    assets_by_id = {asset["asset_id"]: asset for asset in current_assets}
    hashes = {asset["source_sha256"] for asset in current_assets}
    source_paths: dict[str, Path] = {}
    for root in roots:
        root = root.resolve()
        for record in candidate_records(root):
            if record.get("quality_status") != "accepted":
                continue
            source_path = resolve_candidate_path(root, record)
            source_sha256, dimensions = inspect_source(source_path)
            if source_sha256 in hashes:
                continue
            captured_at, captured_date = parse_captured_at(record["captured_at"])
            if captured_date < CUTOFF:
                continue
            areas = normalize_areas(record.get("scene_area", record.get("scene_area_ids")))
            if not areas:
                raise ValueError(f"候选素材缺少可识别区域: {record.get('candidate_id')}")
            asset_id = normalize_asset_id(str(record.get("candidate_id", "")), source_sha256)
            if asset_id in assets_by_id:
                asset_id = f"{asset_id}_{source_sha256[:8].upper()}"
            asset = {
                "asset_id": asset_id,
                "source_platform": record["source_platform"],
                "source_page_url": record["source_page_url"],
                "source_post_id": record.get("source_post_id"),
                "source_image_index": record.get("source_image_index"),
                "author": record.get("author") or "来源页作者",
                "captured_at": captured_at,
                "date_basis": record.get("date_basis", "post_published_at"),
                "accessed_at": record.get("accessed_at", date.today().isoformat()),
                "scene_area_ids": areas,
                "scene_name": record["scene_name"],
                "road_visible": bool(record["road_visible"]),
                "route_ids": sorted(set(record.get("route_ids", []))),
                "slot_recommendations": normalize_slots(
                    record.get("slot_recommendations", [])
                ),
                "quality_status": "accepted",
                "usage_scope": "competition_demo_only",
                "source_file": str(source_path),
                "source_sha256": source_sha256,
                "source_dimensions": dimensions,
                "notes": record.get("notes", ""),
            }
            assets_by_id[asset_id] = asset
            hashes.add(source_sha256)
            source_paths[asset_id] = source_path
    return sorted(assets_by_id.values(), key=lambda item: item["asset_id"]), source_paths


def route_areas(route: dict[str, Any]) -> set[str]:
    return set(normalize_areas(route["popular_area_ids"]))


def asset_matches_route(asset: dict[str, Any], route: dict[str, Any]) -> bool:
    return bool(set(asset["scene_area_ids"]) & route_areas(route)) or route[
        "route_id"
    ] in asset.get("route_ids", [])


def trim_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = list(assets)
    while len(selected) > MAX_UNIQUE_ASSETS:
        area_counts = Counter(
            area_id for asset in selected for area_id in asset["scene_area_ids"]
        )
        road_counts = Counter(
            area_id
            for asset in selected
            if asset["road_visible"]
            for area_id in asset["scene_area_ids"]
        )
        droppable = [
            asset
            for asset in selected
            if all(area_counts[area_id] > 3 for area_id in asset["scene_area_ids"])
            and (
                not asset["road_visible"]
                or all(road_counts[area_id] > 2 for area_id in asset["scene_area_ids"])
            )
        ]
        if not droppable:
            raise ValueError("无法在保留区域覆盖的前提下缩减素材集")
        removed = max(
            droppable,
            key=lambda asset: (
                0 if asset["source_platform"] == "existing_curated_source" else 1,
                1 if not asset["road_visible"] else 0,
                min(area_counts[area_id] for area_id in asset["scene_area_ids"]),
                -len(asset.get("route_ids", [])),
                asset["asset_id"],
            ),
        )
        selected.remove(removed)
    return sorted(selected, key=lambda asset: asset["asset_id"])


def assignment_sort_key(
    asset: dict[str, Any],
    route: dict[str, Any],
    slot: str,
    usage: Counter[str],
    cover_usage: Counter[str],
    used_posts: Counter[str],
    used_areas: Counter[str],
) -> tuple[Any, ...]:
    post_key = asset.get("source_post_id") or asset["source_page_url"]
    areas = set(asset["scene_area_ids"]) & route_areas(route)
    return (
        usage[asset["asset_id"]],
        cover_usage[asset["asset_id"]] if slot == "cover" else 0,
        0 if route["route_id"] in asset.get("route_ids", []) else 1,
        0 if slot in asset.get("slot_recommendations", []) else 1,
        used_posts[post_key],
        min((used_areas[area] for area in areas), default=0),
        0 if asset["road_visible"] else 1,
        asset["asset_id"],
    )


def assign_assets(
    routes: list[dict[str, Any]], assets: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    eligible_by_route = {
        route["route_id"]: [
            asset for asset in assets if asset_matches_route(asset, route)
        ]
        for route in routes
    }
    for route in routes:
        eligible = eligible_by_route[route["route_id"]]
        if len(eligible) < 3 or sum(asset["road_visible"] for asset in eligible) < 2:
            raise ValueError(f"路线候选素材不足: {route['route_id']} {route['route_name']}")

    usage: Counter[str] = Counter()
    cover_usage: Counter[str] = Counter()
    assignments: dict[str, dict[str, str]] = {}
    ordered_routes = sorted(
        routes,
        key=lambda route: (len(eligible_by_route[route["route_id"]]), route["route_id"]),
    )
    for route in ordered_routes:
        route_id = route["route_id"]
        selected: dict[str, str] = {}
        used_posts: Counter[str] = Counter()
        used_areas: Counter[str] = Counter()
        scenery_count = 0
        for slot in SLOTS:
            candidates = []
            for asset in eligible_by_route[route_id]:
                asset_id = asset["asset_id"]
                if asset_id in selected.values() or usage[asset_id] >= MAX_TOTAL_REUSE:
                    continue
                if slot == "cover" and (
                    not asset["road_visible"] or cover_usage[asset_id] >= MAX_COVER_REUSE
                ):
                    continue
                if not asset["road_visible"] and scenery_count >= 1:
                    continue
                candidates.append(asset)
            if not candidates:
                raise ValueError(f"路线槽位分配失败: {route_id}:{slot}")
            asset = min(
                candidates,
                key=lambda item: assignment_sort_key(
                    item,
                    route,
                    slot,
                    usage,
                    cover_usage,
                    used_posts,
                    used_areas,
                ),
            )
            asset_id = asset["asset_id"]
            selected[slot] = asset_id
            usage[asset_id] += 1
            if slot == "cover":
                cover_usage[asset_id] += 1
            if not asset["road_visible"]:
                scenery_count += 1
            post_key = asset.get("source_post_id") or asset["source_page_url"]
            used_posts[post_key] += 1
            for area_id in set(asset["scene_area_ids"]) & route_areas(route):
                used_areas[area_id] += 1
        assignments[route_id] = selected
    return assignments


def apply_route_slot_overrides(assignments: dict[str, dict[str, str]]) -> None:
    for route_id, overrides in ROUTE_SLOT_OVERRIDES.items():
        assigned = assignments[route_id]
        for target_slot, asset_id in overrides.items():
            source_slot = next(
                (slot for slot, assigned_id in assigned.items() if assigned_id == asset_id),
                None,
            )
            if source_slot is None:
                raise ValueError(f"固定图片未分配到对应路线: {route_id} {asset_id}")
            assigned[target_slot], assigned[source_slot] = (
                assigned[source_slot],
                assigned[target_slot],
            )


def materialize(source_path: Path, output_path: Path) -> dict[str, Any]:
    with Image.open(source_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    needs_write = source_path.resolve() != output_path.resolve() or max(image.size) > 1280
    if needs_write:
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        same_path = source_path.resolve() == output_path.resolve()
        save_path = (
            output_path.with_name(f".{output_path.stem}.tmp.webp")
            if same_path
            else output_path
        )
        image.save(save_path, "WEBP", quality=80, method=6)
        if same_path:
            save_path.replace(output_path)
    with Image.open(output_path) as opened:
        dimensions = list(ImageOps.exif_transpose(opened).size)
    payload = output_path.read_bytes()
    return {
        "webp_dimensions": dimensions,
        "webp_bytes": len(payload),
        "webp_sha256": hashlib.sha256(payload).hexdigest(),
    }


def registry_source_path(asset: dict[str, Any], imported: dict[str, Path]) -> Path:
    if asset["asset_id"] in imported:
        return imported[asset["asset_id"]]
    path = Path(asset["source_file"])
    return path if path.is_absolute() else REPO_ROOT / path


def build_manifest(
    routes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    assignments: dict[str, dict[str, str]],
    imported: dict[str, Path],
) -> dict[str, Any]:
    used_ids = {asset_id for slots in assignments.values() for asset_id in slots.values()}
    assets_by_id = {asset["asset_id"]: asset for asset in assets}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    asset_manifest: dict[str, dict[str, Any]] = {}
    for asset_id in sorted(used_ids):
        asset = assets_by_id[asset_id]
        output_path = OUTPUT_DIR / f"{asset_id}.webp"
        image_info = materialize(registry_source_path(asset, imported), output_path)
        asset["source_file"] = str(output_path.relative_to(REPO_ROOT)).replace("\\", "/")
        asset_manifest[asset_id] = {
            **asset,
            "src": f"./assets/routes/{asset_id}.webp",
            **image_info,
        }

    desired = {f"{asset_id}.webp" for asset_id in used_ids}
    for stale in OUTPUT_DIR.glob("*.webp"):
        if stale.name not in desired:
            stale.unlink()

    route_manifest: dict[str, dict[str, Any]] = {}
    for route in routes:
        route_id = route["route_id"]
        slots: dict[str, dict[str, Any]] = {}
        for slot in SLOTS:
            asset_id = assignments[route_id][slot]
            asset = assets_by_id[asset_id]
            matched_areas = sorted(set(asset["scene_area_ids"]) & route_areas(route))
            status = (
                "verified_route_hint"
                if route_id in asset.get("route_ids", [])
                else "verified_area_relevance"
            )
            slots[slot] = {
                "asset_id": asset_id,
                "src": f"./assets/routes/{asset_id}.webp",
                "verification_status": status,
                "matched_area_ids": matched_areas,
                "evidence": [asset["scene_name"], asset["source_page_url"]],
            }
        route_manifest[route_id] = {
            "route_name": route["route_name"],
            "mode": route["route_mode"],
            "slots": slots,
        }

    usage = Counter(
        asset_id for slots in assignments.values() for asset_id in slots.values()
    )
    cover_usage = Counter(slots["cover"] for slots in assignments.values())
    area_only_route_ids = [
        route_id
        for route_id, route in route_manifest.items()
        if all(
            slot["verification_status"] == "verified_area_relevance"
            for slot in route["slots"].values()
        )
    ]
    routes_with_pure_scenery = [
        route_id
        for route_id, slots in assignments.items()
        if any(not assets_by_id[asset_id]["road_visible"] for asset_id in slots.values())
    ]
    total_bytes = sum(asset["webp_bytes"] for asset in asset_manifest.values())
    return {
        "version": 2,
        "generated_at": date.today().isoformat(),
        "summary": {
            "routes_total": len(routes),
            "slots_total": len(routes) * len(SLOTS),
            "unique_webp_assets": len(asset_manifest),
            "filled_slots": len(routes) * len(SLOTS),
            "missing_slots": 0,
            "routes_three_slots": len(routes),
            "routes_with_cover": len(routes),
            "routes_without_media": 0,
            "road_visible_slots": sum(
                usage[asset_id]
                for asset_id, asset in asset_manifest.items()
                if asset["road_visible"]
            ),
            "pure_scenery_slots": sum(
                usage[asset_id]
                for asset_id, asset in asset_manifest.items()
                if not asset["road_visible"]
            ),
            "max_asset_reuse": max(usage.values()),
            "max_cover_reuse": max(cover_usage.values()),
            "total_webp_bytes": total_bytes,
            "area_only_route_ids": area_only_route_ids,
            "routes_with_pure_scenery": routes_with_pure_scenery,
            "missing_route_ids": [],
            "missing_slots_by_route": {},
        },
        "routes": route_manifest,
        "assets": asset_manifest,
    }


def main() -> None:
    args = parse_args()
    routes = load_json(ROUTE_CATALOG)
    assets, imported = import_candidates(load_registry(), args.import_root)
    assets = trim_assets(assets)
    assignments = assign_assets(routes, assets)
    apply_route_slot_overrides(assignments)
    used_ids = {asset_id for slots in assignments.values() for asset_id in slots.values()}
    summary = {
        "registry_assets": len(assets),
        "assigned_unique_assets": len(used_ids),
        "filled_slots": len(assignments) * len(SLOTS),
    }
    if args.check_only:
        print(json.dumps(summary, ensure_ascii=False))
        return
    manifest = build_manifest(routes, assets, assignments, imported)
    used_registry_assets = [asset for asset in assets if asset["asset_id"] in used_ids]
    write_json(
        REGISTRY_PATH,
        {
            "version": 1,
            "updated_at": date.today().isoformat(),
            "cutoff_date": CUTOFF.isoformat(),
            "assets": used_registry_assets,
        },
    )
    write_json(MANIFEST_PATH, manifest)
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
