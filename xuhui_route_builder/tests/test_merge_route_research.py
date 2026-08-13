import json

import pytest

from xuhui_route_builder.route_research import merge_research_drafts


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
