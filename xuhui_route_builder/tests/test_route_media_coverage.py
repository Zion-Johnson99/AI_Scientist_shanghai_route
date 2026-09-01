from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "data" / "seeds" / "route_photo_registry.json"
MANIFEST_PATH = PROJECT_ROOT / "data" / "web" / "route_media_manifest.json"
ROUTE_CATALOG_PATH = PROJECT_ROOT / "data" / "web" / "route_catalog.json"
CUTOFF = date(2016, 8, 31)
SLOTS = ("cover", "context", "detail")


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def captured_date(value: str) -> date:
    if len(value) == 4:
        return date(int(value), 1, 1)
    return date.fromisoformat(value)


def test_registry_has_enough_current_traceable_assets() -> None:
    registry = load_json(REGISTRY_PATH)
    assert isinstance(registry, dict)
    assets = registry["assets"]

    ids = [asset["asset_id"] for asset in assets]
    assert len(ids) == len(set(ids))
    assert 150 <= len(ids) <= 180

    for asset in assets:
        observed = captured_date(asset["captured_at"])
        assert CUTOFF <= observed <= date.today()
        assert asset["date_basis"] in {
            "taken_at",
            "post_published_at",
            "source_metadata",
        }
        assert asset["source_page_url"].startswith(("https://", "http://"))
        assert asset["accessed_at"]
        assert isinstance(asset["road_visible"], bool)
        assert asset["quality_status"] == "accepted"
        assert asset["scene_area_ids"]
        assert asset["scene_name"]


def test_manifest_fills_all_route_slots_with_bounded_reuse() -> None:
    catalog = load_json(ROUTE_CATALOG_PATH)
    manifest = load_json(MANIFEST_PATH)
    assert isinstance(catalog, list)
    assert isinstance(manifest, dict)
    assert set(manifest["routes"]) == {route["route_id"] for route in catalog}

    usage: Counter[str] = Counter()
    cover_usage: Counter[str] = Counter()
    for route in manifest["routes"].values():
        slots = route["slots"]
        assert set(slots) == set(SLOTS)
        assert all(slots[slot] is not None for slot in SLOTS)
        asset_ids = [slots[slot]["asset_id"] for slot in SLOTS]
        assert len(set(asset_ids)) == len(SLOTS)
        assert (
            sum(
                not manifest["assets"][asset_id]["road_visible"]
                for asset_id in asset_ids
            )
            <= 1
        )
        usage.update(asset_ids)
        cover_usage.update([slots["cover"]["asset_id"]])

    assert sum(usage.values()) == 270
    assert len(usage) >= 150
    assert len(cover_usage) >= 80
    assert max(usage.values()) <= 4
    assert max(cover_usage.values()) <= 2
    assert manifest["summary"]["filled_slots"] == 270
    assert manifest["summary"]["missing_slots"] == 0
    assert manifest["summary"]["routes_three_slots"] == 90
    assert manifest["summary"]["routes_with_cover"] == 90
    assert manifest["summary"]["routes_without_media"] == 0


def test_xujiahui_sports_route_uses_track_photo_as_cover() -> None:
    manifest = load_json(MANIFEST_PATH)
    assert isinstance(manifest, dict)
    slots = manifest["routes"]["XH_WALK_0007"]["slots"]

    assert slots["cover"]["asset_id"] == "XH_IMG_XHS_69676538000000001A035E41_03"
    assert slots["detail"]["asset_id"] == "XH_IMG_XHS_66C750C4000000001D016439_07"


def test_manifest_webp_assets_are_valid_and_deduplicated() -> None:
    manifest = load_json(MANIFEST_PATH)
    assert isinstance(manifest, dict)
    content_hashes: set[str] = set()
    for asset_id, asset in manifest["assets"].items():
        path = PROJECT_ROOT / "web" / asset["src"].removeprefix("./")
        assert path.is_file(), asset_id
        assert asset["webp_sha256"] not in content_hashes
        content_hashes.add(asset["webp_sha256"])
        header = path.read_bytes()[:12]
        assert header[:4] == b"RIFF"
        assert header[8:12] == b"WEBP"
        assert min(asset["webp_dimensions"]) >= 600
