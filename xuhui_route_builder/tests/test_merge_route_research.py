import json

import pytest

from xuhui_route_builder.route_research import (
    PROTECTED_GEOMETRY_IDS,
    merge_research_drafts,
    merge_route_optimizations,
)


def test_merge_research_drafts_writes_one_validated_collection(tmp_path) -> None:
    research = tmp_path / "research"
    research.mkdir()
    for mode in ("walk", "run", "bike"):
        payload = [{"seed_id": f"{mode}-{index}", "route_mode": mode} for index in range(30)]
        (research / f"{mode}_route_candidates_0813.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    target = tmp_path / "route_seed_drafts.json"
    merged = merge_research_drafts(research, target, lambda items: None)

    assert len(merged) == 90
    assert json.loads(target.read_text(encoding="utf-8")) == merged


def test_merge_research_drafts_preserves_target_when_preflight_fails(tmp_path) -> None:
    research = tmp_path / "research"
    research.mkdir()
    (research / "walk_route_candidates_0813.json").write_text("[]", encoding="utf-8")
    target = tmp_path / "route_seed_drafts.json"
    target.write_text("old-content", encoding="utf-8")

    with pytest.raises(ValueError, match="missing research files"):
        merge_research_drafts(research, target, lambda items: None)

    assert target.read_text(encoding="utf-8") == "old-content"


def test_merge_route_optimizations_normalizes_three_mode_results(tmp_path) -> None:
    research = tmp_path / "research"
    research.mkdir()
    base = []
    prefixes = {"walk": "WALK", "run": "RUN", "bike": "BIKE"}
    first_numbers = {"walk": 1, "run": 31, "bike": 61}
    for mode in ("walk", "run", "bike"):
        optimized = []
        for offset in range(30):
            number = first_numbers[mode] + offset
            route_id = f"XH_{prefixes[mode]}_{number:04d}"
            seed_id = f"{mode}-{offset}"
            base.append({
                "seed_id": seed_id,
                "route_name": f"旧路线{number}",
                "route_mode": mode,
                "distance_level": "3km",
                "target_distance_m": 3000 if mode != "bike" else 7000,
                "region_zone": "徐汇区",
                "start_hint": "旧起点",
                "end_hint": "旧终点",
                "waypoint_hints": [],
                "tags": ["测试"],
                "reason": "旧设计",
                "source_name": "徐汇区人民政府",
                "source_url": "https://www.xuhui.gov.cn/base",
                "source_accessed_at": "2026-08-13",
                "confidence": "高",
                "ordered_nodes": [{"node_name": "旧起点", "lng_gcj02": 121.44, "lat_gcj02": 31.18}, {"node_name": "旧终点", "lng_gcj02": 121.45, "lat_gcj02": 31.19}],
                "allowed_modes": [mode],
                "source_level": "A",
                "evidence_note": "旧证据",
                "access_restrictions": ["旧限制"],
            })
            optimized.append({
                "route_id": route_id,
                "seed_id": seed_id,
                "route_name": f"新路线{number}",
                "route_mode": mode,
                "target_distance_m": 3000 if mode != "bike" else 7000,
                "route_shape": "one_way",
                "start_location": {"name": "新起点", "lng_gcj02": 121.44, "lat_gcj02": 31.18, "source": "核实"},
                "end_location": {"name": "新终点", "lng_gcj02": 121.45, "lat_gcj02": 31.19, "source": "核实"},
                "ordered_nodes": [{"name": "新起点", "lng_gcj02": 121.44, "lat_gcj02": 31.18}, {"name": "新终点", "lng_gcj02": 121.45, "lat_gcj02": 31.19}],
                "waypoint_names": [],
                "amenities": [],
                "amenity_ids": [],
                "popular_area_ids": ["west_bund"],
                "preference_search_status": {
                    "coffee": "verified",
                    "park_gate": "verified",
                    "toilet": "no_verified_match",
                    "convenience": "needs_review",
                },
                "preference_hits": ["coffee", "park_gate"],
                "geometry_action": "preserve" if route_id in PROTECTED_GEOMETRY_IDS else "regenerate",
                "geometry_source": "amap_direction",
                "evidence_note": "新证据",
                "access_restrictions": ["新限制"],
                "design_rationale": "连续单程",
                "risk_flags": [],
                "source_records": [{"source_name": "徐汇区人民政府", "source_url": "https://www.xuhui.gov.cn/new", "accessed_at": "2026-08-15"}],
            })
        (research / f"{mode}_route_optimization_0815.json").write_text(json.dumps(optimized, ensure_ascii=False), encoding="utf-8")
    base_path = tmp_path / "route_seeds.json"
    base_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")

    merged = merge_route_optimizations(research, base_path, base_path)

    assert len(merged) == 90
    assert merged[0]["route_shape"] == "one_way"
    assert merged[0]["start_location"]["name"] == "新起点"
    assert merged[0]["ordered_nodes"][0]["node_name"] == "新起点"
    assert merged[0]["evidence_note"] == "新证据"
    assert merged[0]["popular_area_ids"] == ["west_bund"]
    assert merged[0]["preference_search_status"]["park_gate"] == "verified"
    assert merged[0]["preference_hits"] == ["coffee", "park_gate"]
    assert merged[0]["geometry_action"] == "preserve"
    assert {
        route_id
        for route_id, route in zip(
            [
                f"XH_{prefixes[item['route_mode']]}_{index:04d}"
                for index, item in enumerate(merged, start=1)
            ],
            merged,
        )
        if route["geometry_action"] == "preserve"
    } == PROTECTED_GEOMETRY_IDS
