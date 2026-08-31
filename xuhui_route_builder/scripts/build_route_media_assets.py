from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_ROOT = Path.home() / "Desktop" / "图片查找工作"
DEFAULT_PACKAGE_ROOT = Path.home() / "Desktop" / "徐汇90条路线图片包"
ROUTE_CATALOG = REPO_ROOT / "data" / "web" / "route_catalog.json"
ROUTE_GEOJSON = REPO_ROOT / "data" / "web" / "xuhui_routes.geojson"
OUTPUT_DIR = REPO_ROOT / "web" / "assets" / "routes"
MANIFEST_PATH = REPO_ROOT / "data" / "web" / "route_media_manifest.json"

SLOTS = ("cover", "context", "detail")
SLOT_NAMES = {"封面": "cover", "路线环境": "context", "地标与终点细节": "detail"}
EXPLICIT_REJECTS = {
    "XH_IMG_XJH_011",
    "XH_IMG_GARDEN_008",
    "XH_IMG_CAOHEJING_002",
}
EXPLICIT_APPROVALS = {"XH_IMG_WESTBUND_012", "XH_IMG_HENGFU_007"}

# 仅纳入已人工完成地点、年代和场景复核的候选。
CURATED_CANDIDATES = {
    "XH_IMG_WESTBUND_001",
    "XH_IMG_WESTBUND_002",
    "XH_IMG_WESTBUND_006",
    "XH_IMG_WESTBUND_011",
    "XH_IMG_WESTBUND_012",
    "XH_IMG_WESTBUND_014",
    "XH_IMG_WESTBUND_016",
    "XH_IMG_GARDEN_002",
    "XH_IMG_GARDEN_003",
    "XH_IMG_GARDEN_004",
    "XH_IMG_GARDEN_005",
    "XH_IMG_GARDEN_010",
    "XH_IMG_GARDEN_011",
    "XH_IMG_XJH_002",
    "XH_IMG_XJH_006",
    "XH_IMG_XJH_007",
    "XH_IMG_LONGHUA_002",
    "XH_IMG_LONGHUA_003",
    "XH_IMG_LONGHUA_004",
    "XH_IMG_LONGHUA_006",
    "XH_IMG_LONGHUA_007",
    "XH_IMG_LONGHUA_009",
    "XH_IMG_HENGFU_001",
    "XH_IMG_HENGFU_007",
    "XH_IMG_HENGFU_009",
    "XH_IMG_CAOHEJING_001",
    "XH_IMG_CAOHEJING_003",
    "XH_IMG_CAOHEJING_004",
    "XH_IMG_KANGJIAN_001",
    "XH_IMG_KANGJIAN_002",
    "XH_IMG_KANGJIAN_003",
    "XH_IMG_KANGJIAN_004",
    "XH_IMG_NANZHAN_001",
    "XH_IMG_NANZHAN_002",
}

# 主图调整与明确的三图组合在此锁定; 避免随候选表顺序漂移。
LOCKED_ASSIGNMENTS = {
    ("XH_WALK_0001", "cover"): "XH_IMG_WESTBUND_016",
    ("XH_WALK_0001", "context"): "XH_IMG_WESTBUND_014",
    ("XH_WALK_0001", "detail"): "XH_IMG_WESTBUND_006",
    ("XH_RUN_0031", "cover"): "XH_IMG_WESTBUND_012",
    ("XH_RUN_0031", "context"): "XH_IMG_WESTBUND_016",
    ("XH_RUN_0031", "detail"): "XH_IMG_WESTBUND_014",
    ("XH_BIKE_0079", "cover"): "XH_IMG_HENGFU_007",
    ("XH_WALK_0025", "cover"): "XH_IMG_COMMONS_183737818",
}

REGISTER_ALIAS = {"XH_IMG_WESTBUND_011": "XH_IMG_WESTBUND_TEST_001"}
PACKAGE_ASSETS = {"XH_IMG_COMMONS_183737818"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成徐汇90条路线的去重 WebP 与媒体清单"
    )
    parser.add_argument("--candidate-root", type=Path, default=DEFAULT_CANDIDATE_ROOT)
    parser.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_candidate_table(root: Path) -> dict[str, dict[str, Any]]:
    checklist = root / "90条路线实景图片检索清单.md"
    row_pattern = re.compile(
        r"^\| (XH_IMG_[^|]+)\.jpg \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$"
    )
    source_pattern = re.compile(r"^\[(.*?)\]\((https?://.*?)\) · (.+)$")
    assets: dict[str, dict[str, Any]] = {}
    for line in checklist.read_text(encoding="utf-8").splitlines():
        row = row_pattern.match(line)
        if not row:
            continue
        asset_id, scene, source, assignment_text, status = row.groups()
        source_match = source_pattern.match(source)
        if not source_match:
            raise ValueError(f"候选图片来源格式无法解析: {asset_id}")
        author, source_page_url, license_name = source_match.groups()
        assignments = []
        for item in assignment_text.split("、"):
            match = re.search(
                r"(XH_(?:WALK|RUN|BIKE)_\d{4}):(cover|context|detail)", item
            )
            if match:
                assignments.append((match.group(1), match.group(2)))
        year_match = re.search(r"(20\d{2}|19\d{2})年", scene)
        assets[asset_id] = {
            "asset_id": asset_id,
            "source_path": root / "images" / "candidates" / f"{asset_id}.jpg",
            "source_collection": "图片查找工作/images/candidates",
            "source_file": f"images/candidates/{asset_id}.jpg",
            "scene_name": scene,
            "author": author,
            "license": license_name,
            "license_url": None,
            "source_page_url": source_page_url,
            "captured_at": year_match.group(1) if year_match else None,
            "candidate_status": status,
            "assignments": assignments,
        }
    return assets


def merge_register(root: Path, assets: dict[str, dict[str, Any]]) -> None:
    register_path = (
        root / "archive" / "legacy-workflow" / "register" / "image_asset_register.json"
    )
    register = {item["asset_id"]: item for item in load_json(register_path)["assets"]}
    for asset_id, asset in assets.items():
        record = register.get(REGISTER_ALIAS.get(asset_id, asset_id))
        if not record:
            continue
        asset["captured_at"] = asset["captured_at"] or record.get("captured_at")
        asset["coordinate_wgs84"] = record.get("coordinate_wgs84")
        asset["coordinate_note"] = record.get("distance_to_route_m")
        asset["composition_note"] = record.get("composition")


def load_package_assets(root: Path) -> dict[str, dict[str, Any]]:
    table_dir = root / "00_说明与总表"
    with (table_dir / "素材来源清单.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        sources = {row["asset_id"]: row for row in csv.DictReader(handle)}
    with (table_dir / "90条路线图片分配总表.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assets: dict[str, dict[str, Any]] = {}
    for asset_id in PACKAGE_ASSETS:
        source = sources[asset_id]
        allocation = next(
            row
            for row in rows
            if row["asset_id"] == asset_id and row["old_visual_fit"] == "full"
        )
        assets[asset_id] = {
            "asset_id": asset_id,
            "source_path": root / Path(allocation["route_image_relative_path"]),
            "source_collection": "徐汇90条路线图片包/01_路线图片",
            "source_file": allocation["route_image_relative_path"],
            "scene_name": source["scene_name"],
            "author": source["author"],
            "license": source["license"],
            "license_url": source["license_url"] or None,
            "source_page_url": source["source_page_url"],
            "captured_at": source["captured_at"],
            "candidate_status": "package_full_reviewed",
            "coordinate_wgs84": source["coordinate_wgs84"] or None,
            "coordinate_note": allocation["location_match_note"],
            "composition_note": allocation["location_match_note"],
            "assignments": [],
        }
    return assets


def captured_year(value: str | None) -> int | None:
    match = re.search(r"(19\d{2}|20\d{2})", value or "")
    return int(match.group(1)) if match else None


def parse_coordinate(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    match = re.match(r"\s*([0-9.]+),([0-9.]+)", value)
    if not match:
        return None
    first, second = map(float, match.groups())
    if first < 90 and second > 90:
        return second, first
    return first, second


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    ee = 0.00669342162296594323
    earth_radius = 6378245.0
    x, y = lng - 105.0, lat - 35.0
    dlat = (
        -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    )
    dlng = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    dlat += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    dlat += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
    dlat += (
        (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    )
    dlng += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    dlng += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
    dlng += (
        (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    )
    radlat = lat / 180 * math.pi
    magic = 1 - ee * math.sin(radlat) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = dlat * 180 / ((earth_radius * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    dlng = dlng * 180 / (earth_radius / sqrt_magic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def point_to_polyline_m(point: tuple[float, float], line: list[list[float]]) -> float:
    lat_radians = math.radians(point[1])
    scale_x = 111320 * math.cos(lat_radians)
    scale_y = 110540
    px, py = point[0] * scale_x, point[1] * scale_y
    best = math.inf
    for start, end in pairwise(line):
        ax, ay = start[0] * scale_x, start[1] * scale_y
        bx, by = end[0] * scale_x, end[1] * scale_y
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        ratio = ((px - ax) * dx + (py - ay) * dy) / denominator if denominator else 0
        ratio = max(0.0, min(1.0, ratio))
        best = min(best, math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy)))
    return best


def verify_assignment(
    asset: dict[str, Any], route: dict[str, Any], line: list[list[float]]
) -> dict[str, Any] | None:
    year = captured_year(asset.get("captured_at"))
    if year is None:
        return None
    if asset["asset_id"] in EXPLICIT_REJECTS:
        return None
    if (
        asset.get("candidate_status") not in {"地点已核验", "package_full_reviewed"}
        and asset["asset_id"] not in EXPLICIT_APPROVALS
    ):
        return None
    limit_m = 150 if route["route_mode"] == "bike" else 100
    coordinate = parse_coordinate(asset.get("coordinate_wgs84"))
    if coordinate:
        distance_m = round(point_to_polyline_m(wgs84_to_gcj02(*coordinate), line), 1)
        if distance_m > limit_m:
            return None
        return {
            "verification_status": "verified_coordinate_distance",
            "distance_to_route_m": distance_m,
            "distance_limit_m": limit_m,
            "evidence": [asset.get("coordinate_wgs84"), asset["source_page_url"]],
        }
    return {
        "verification_status": "verified_two_evidence",
        "distance_to_route_m": None,
        "distance_limit_m": limit_m,
        "evidence": [
            f"场景说明：{asset['scene_name']}",
            f"来源页：{asset['source_page_url']}",
        ],
    }


def build_proposals(
    assets: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    proposals: dict[tuple[str, str], list[str]] = defaultdict(list)
    for asset_id in sorted(CURATED_CANDIDATES):
        for route_id, slot in assets[asset_id]["assignments"]:
            proposals[(route_id, slot)].append(asset_id)
    for key, asset_id in LOCKED_ASSIGNMENTS.items():
        proposals[key] = [asset_id]
    for (route_id, locked_slot), locked_asset in LOCKED_ASSIGNMENTS.items():
        for slot in SLOTS:
            if slot != locked_slot and (route_id, slot) in proposals:
                proposals[(route_id, slot)] = [
                    item for item in proposals[(route_id, slot)] if item != locked_asset
                ]
    return proposals


def compact_slots(
    selected_slots: dict[tuple[str, str], tuple[str, dict[str, Any]]],
    assets: dict[str, dict[str, Any]],
) -> tuple[dict[tuple[str, str], tuple[str, dict[str, Any]]], list[str]]:
    route_items: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for (route_id, slot), item in sorted(
        selected_slots.items(), key=lambda pair: (pair[0][0], SLOTS.index(pair[0][1]))
    ):
        if all(existing[0] != item[0] for existing in route_items[route_id]):
            route_items[route_id].append(item)

    cover_candidates = {
        route_id: sorted(
            items,
            key=lambda item: proposal_priority(assets[item[0]]),
            reverse=True,
        )
        for route_id, items in route_items.items()
    }
    assigned_cover: dict[str, str] = {}
    asset_slots: dict[str, list[str | None]] = defaultdict(lambda: [None, None, None])

    def assign(route_id: str, seen: set[tuple[str, int]]) -> bool:
        for asset_id, _ in cover_candidates[route_id]:
            for index, occupant in enumerate(asset_slots[asset_id]):
                key = (asset_id, index)
                if key in seen:
                    continue
                seen.add(key)
                if occupant is None or assign(occupant, seen):
                    asset_slots[asset_id][index] = route_id
                    assigned_cover[route_id] = asset_id
                    return True
        return False

    dropped_routes: list[str] = []
    for route_id in sorted(
        route_items, key=lambda item: (len(route_items[item]), item)
    ):
        if not assign(route_id, set()):
            dropped_routes.append(route_id)

    compacted: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for route_id, items in route_items.items():
        if route_id in dropped_routes:
            continue
        cover_asset = assigned_cover[route_id]
        ordered = [item for item in items if item[0] == cover_asset]
        ordered.extend(item for item in items if item[0] != cover_asset)
        for slot, item in zip(SLOTS, ordered):
            compacted[(route_id, slot)] = item
    return compacted, dropped_routes


def proposal_priority(asset: dict[str, Any]) -> tuple[int, int, str]:
    year = captured_year(asset.get("captured_at")) or 0
    return (1 if year >= 2020 else 0, year, asset["asset_id"])


def materialize(asset: dict[str, Any], output_path: Path) -> dict[str, Any]:
    source_path = asset["source_path"]
    source_bytes = source_path.read_bytes()
    original_sha256 = hashlib.sha256(source_bytes).hexdigest()
    with Image.open(source_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        original_size = image.size
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        image.save(output_path, "WEBP", quality=82, method=6)
        output_size = image.size
    return {
        "original_sha256": original_sha256,
        "original_dimensions": list(original_size),
        "webp_dimensions": list(output_size),
        "webp_bytes": output_path.stat().st_size,
        "webp_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }


def main() -> None:
    args = parse_args()
    routes = load_json(ROUTE_CATALOG)
    route_by_id = {route["route_id"]: route for route in routes}
    features = load_json(ROUTE_GEOJSON)["features"]
    lines = {
        feature["properties"]["route_id"]: feature["geometry"]["coordinates"]
        for feature in features
    }

    assets = parse_candidate_table(args.candidate_root)
    merge_register(args.candidate_root, assets)
    assets.update(load_package_assets(args.package_root))
    selected_ids = CURATED_CANDIDATES | PACKAGE_ASSETS
    missing_files = [
        str(assets[item]["source_path"])
        for item in selected_ids
        if not assets[item]["source_path"].is_file()
    ]
    if missing_files:
        raise FileNotFoundError("\n".join(missing_files))

    proposals = build_proposals(assets)
    selected_slots: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    usage: Counter[str] = Counter()
    cover_usage: Counter[str] = Counter()
    for key, candidates in sorted(proposals.items()):
        route_id, slot = key
        ordered = sorted(
            candidates, key=lambda item: proposal_priority(assets[item]), reverse=True
        )
        for asset_id in ordered:
            if usage[asset_id] >= 8 or (slot == "cover" and cover_usage[asset_id] >= 3):
                continue
            verification = verify_assignment(
                assets[asset_id], route_by_id[route_id], lines[route_id]
            )
            if verification is None:
                continue
            selected_slots[key] = (asset_id, verification)
            usage[asset_id] += 1
            if slot == "cover":
                cover_usage[asset_id] += 1
            break

    selected_slots, dropped_cover_routes = compact_slots(selected_slots, assets)

    used_ids = sorted({asset_id for asset_id, _ in selected_slots.values()})
    if args.check_only:
        print(
            json.dumps(
                {"used_assets": len(used_ids), "filled_slots": len(selected_slots)},
                ensure_ascii=False,
            )
        )
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    asset_manifest: dict[str, dict[str, Any]] = {}
    content_hashes: dict[str, str] = {}
    canonical_map: dict[str, str] = {}
    for asset_id in used_ids:
        source_hash = hashlib.sha256(
            assets[asset_id]["source_path"].read_bytes()
        ).hexdigest()
        canonical_id = content_hashes.setdefault(source_hash, asset_id)
        canonical_map[asset_id] = canonical_id
        if canonical_id != asset_id:
            continue
        output_path = OUTPUT_DIR / f"{asset_id}.webp"
        image_info = materialize(assets[asset_id], output_path)
        asset = assets[asset_id]
        asset_manifest[asset_id] = {
            "asset_id": asset_id,
            "src": f"./assets/routes/{asset_id}.webp",
            "scene_name": asset["scene_name"],
            "source_collection": asset["source_collection"],
            "source_file": asset["source_file"],
            "author": asset["author"],
            "license": asset["license"],
            "license_url": asset.get("license_url"),
            "source_page_url": asset["source_page_url"],
            "captured_at": asset["captured_at"],
            "coordinate_wgs84": asset.get("coordinate_wgs84"),
            "verification_status": "verified_for_assigned_routes",
            **image_info,
        }
    desired_files = {f"{asset_id}.webp" for asset_id in asset_manifest}
    for stale_path in OUTPUT_DIR.glob("*.webp"):
        if stale_path.name not in desired_files:
            stale_path.unlink()

    route_manifest: dict[str, dict[str, Any]] = {}
    for route in routes:
        route_id = route["route_id"]
        slots: dict[str, Any] = {slot: None for slot in SLOTS}
        for slot in SLOTS:
            selected = selected_slots.get((route_id, slot))
            if not selected:
                continue
            asset_id, verification = selected
            canonical_id = canonical_map[asset_id]
            slots[slot] = {
                "asset_id": canonical_id,
                "src": f"./assets/routes/{canonical_id}.webp",
                **verification,
            }
        route_manifest[route_id] = {
            "route_name": route["route_name"],
            "mode": route["route_mode"],
            "slots": slots,
        }

    filled_slots = sum(
        value is not None
        for route in route_manifest.values()
        for value in route["slots"].values()
    )
    routes_three = [
        route_id
        for route_id, route in route_manifest.items()
        if all(route["slots"].values())
    ]
    routes_cover = [
        route_id
        for route_id, route in route_manifest.items()
        if route["slots"]["cover"]
    ]
    routes_empty = [
        route_id
        for route_id, route in route_manifest.items()
        if not any(route["slots"].values())
    ]
    missing_by_route = {
        route_id: [slot for slot, value in route["slots"].items() if value is None]
        for route_id, route in route_manifest.items()
        if not all(route["slots"].values())
    }
    license_distribution = dict(
        sorted(Counter(asset["license"] for asset in asset_manifest.values()).items())
    )
    total_bytes = sum(asset["webp_bytes"] for asset in asset_manifest.values())
    manifest = {
        "version": 1,
        "generated_at": date.today().isoformat(),
        "summary": {
            "routes_total": len(route_manifest),
            "slots_total": len(route_manifest) * len(SLOTS),
            "unique_webp_assets": len(asset_manifest),
            "filled_slots": filled_slots,
            "missing_slots": len(route_manifest) * len(SLOTS) - filled_slots,
            "routes_three_slots": len(routes_three),
            "routes_with_cover": len(routes_cover),
            "routes_without_media": len(routes_empty),
            "total_webp_bytes": total_bytes,
            "license_distribution": license_distribution,
            "routes_dropped_by_cover_reuse_limit": dropped_cover_routes,
            "missing_route_ids": routes_empty,
            "missing_slots_by_route": missing_by_route,
        },
        "routes": route_manifest,
        "assets": asset_manifest,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
