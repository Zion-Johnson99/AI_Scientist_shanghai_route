import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import xuhui_route_builder.cli as cli_module
from xuhui_route_builder.cli import resolve_seed_drafts, validate_seeds
from xuhui_route_builder.routes import resolve_node_query


class DraftClient:
    def __init__(self, fail_query: str | None = None) -> None:
        self.fail_query = fail_query
        self.calls: list[tuple[str, str]] = []

    def place_text_v5(self, query: str, region: str = "310104"):
        self.calls.append((query, region))
        if query == self.fail_query:
            raise RuntimeError("forced failure")
        drafts_path = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
        drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
        expected_ids = {
            node["query"]: node["expected_poi_id"]
            for draft in drafts
            for node in draft["nodes"]
            if node.get("expected_poi_id")
        }
        return SimpleNamespace(
            status="1",
            raw_path=f"raw/{len(self.calls)}.json",
            payload={
                "pois": [
                    {
                        "id": expected_ids.get(query, f"REAL{len(self.calls):04d}"),
                        "name": query,
                        "adcode": "310104",
                        "location": f"121.{4000 + len(self.calls):04d},31.{1000 + len(self.calls):04d}",
                    }
                ]
            },
        )


def test_route_seed_drafts_have_exact_balanced_strict_schema() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    drafts = json.loads(path.read_text(encoding="utf-8"))

    assert len(drafts) == 15
    assert {mode: sum(item["route_mode"] == mode for item in drafts) for mode in ("run", "walk", "bike")} == {
        "run": 5,
        "walk": 5,
        "bike": 5,
    }
    for draft in drafts:
        assert draft["source_level"] in {"A", "B", "C"}
        assert draft["source_url"].startswith("https://")
        assert draft["access_restrictions"]
        assert len(draft["nodes"]) >= 2
        for node in draft["nodes"]:
            assert set(node).issubset({"query", "expected_name", "expected_poi_id"})
            assert node["query"] and node["expected_name"]
            assert "lng_gcj02" not in node and "poi_id" not in node


def test_route_seed_drafts_do_not_use_out_of_district_lupu_bridge_poi() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    drafts = json.loads(path.read_text(encoding="utf-8"))

    assert all(node["expected_name"] != "卢浦大桥" for draft in drafts for node in draft["nodes"])


def test_resolve_node_query_returns_strict_real_node_and_contextual_error() -> None:
    client = DraftClient()
    node, raw_path = resolve_node_query("入口", "入口", client, None, "seed-1", 2)

    assert node.poi_id == "REAL0001"
    assert node.lng_gcj02 is not None
    assert raw_path == "raw/1.json"
    assert client.calls == [("入口", "310104")]

    with pytest.raises(ValueError, match=r"seed_id=seed-1.*node_index=3.*坏入口"):
        resolve_node_query("坏入口", "坏入口", DraftClient(fail_query="坏入口"), None, "seed-1", 3)


def test_repository_raw_paths_are_persisted_as_relative_paths(tmp_path: Path) -> None:
    raw_path = tmp_path / "data" / "raw" / "amap" / "walking_v2_test.json"

    assert cli_module._portable_raw_path(tmp_path, str(raw_path)) == "data/raw/amap/walking_v2_test.json"


def test_resolve_seed_drafts_writes_strict_seeds_and_validate_seeds(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "route_seed_drafts.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    seeds = resolve_seed_drafts(tmp_path, DraftClient())
    validated = validate_seeds(tmp_path)

    assert len(seeds) == len(validated) == 15
    assert all(node.poi_id and node.lng_gcj02 is not None for seed in seeds for node in seed.ordered_nodes)
    assert all("POI解析响应:" in seed.evidence_note for seed in seeds)
    assert all(str(tmp_path) not in seed.evidence_note for seed in seeds)
    persisted = json.loads((seed_dir / "route_seeds.json").read_text(encoding="utf-8"))
    assert len(persisted) == 15


def test_resolve_seed_drafts_does_not_overwrite_on_failure(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    drafts = json.loads(source.read_text(encoding="utf-8"))
    (seed_dir / "route_seed_drafts.json").write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")
    target = seed_dir / "route_seeds.json"
    target.write_text("old-content", encoding="utf-8")
    failing_query = drafts[2]["nodes"][1]["query"]

    with pytest.raises(ValueError):
        resolve_seed_drafts(tmp_path, DraftClient(fail_query=failing_query))

    assert target.read_text(encoding="utf-8") == "old-content"
    assert not (seed_dir / "route_seeds.json.tmp").exists()


def test_validate_seeds_rejects_wrong_mode_counts_or_missing_restrictions(tmp_path: Path) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    drafts = json.loads(source.read_text(encoding="utf-8"))
    drafts[0]["route_mode"] = "walk"
    drafts[0]["allowed_modes"] = ["walk"]
    drafts[1]["access_restrictions"] = []
    (seed_dir / "route_seed_drafts.json").write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        resolve_seed_drafts(tmp_path, DraftClient())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda drafts: drafts[0].update({"unexpected": True}), "extra"),
        (lambda drafts: drafts[1].update({"seed_id": drafts[0]["seed_id"]}), "seed_id"),
        (lambda drafts: drafts[1].update({"route_name": drafts[0]["route_name"]}), "route_name"),
        (lambda drafts: drafts[0].update({"source_name": ""}), "source_name"),
        (lambda drafts: drafts[0].update({"evidence_note": ""}), "evidence_note"),
        (lambda drafts: drafts[0].update({"allowed_modes": ["walk"]}), "allowed_modes"),
        (lambda drafts: drafts[0]["nodes"][0].update({"extra": "bad"}), "nodes"),
    ],
)
def test_draft_preflight_rejects_invalid_collection_before_api_calls(tmp_path: Path, mutate, message: str) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    drafts = json.loads(source.read_text(encoding="utf-8"))
    mutate(drafts)
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "route_seed_drafts.json").write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")
    client = DraftClient()

    with pytest.raises(ValueError, match=rf"draft index=.*seed_id=.*{message}"):
        resolve_seed_drafts(tmp_path, client)
    assert client.calls == []


def test_atomic_replace_failure_preserves_existing_target_and_cleans_temp(tmp_path: Path, monkeypatch) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "route_seed_drafts.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    target = seed_dir / "route_seeds.json"
    target.write_text("old-content", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(cli_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        resolve_seed_drafts(tmp_path, DraftClient())

    assert target.read_text(encoding="utf-8") == "old-content"
    assert list(seed_dir.glob(".route_seeds.*.tmp")) == []


def test_atomic_write_failure_preserves_existing_target_and_cleans_temp(tmp_path: Path, monkeypatch) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "route_seed_drafts.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    target = seed_dir / "route_seeds.json"
    target.write_text("old-content", encoding="utf-8")

    def fail_dump(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(cli_module.json, "dump", fail_dump)
    with pytest.raises(OSError, match="write failed"):
        resolve_seed_drafts(tmp_path, DraftClient())

    assert target.read_text(encoding="utf-8") == "old-content"
    assert list(seed_dir.glob(".route_seeds.*.tmp")) == []


def test_atomic_write_uses_a_unique_temp_name_for_each_run(tmp_path: Path, monkeypatch) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seed_drafts.json"
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "route_seed_drafts.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    sources: list[Path] = []
    real_replace = cli_module.os.replace

    def capture_replace(source_path, target_path):
        sources.append(Path(source_path))
        real_replace(source_path, target_path)

    monkeypatch.setattr(cli_module.os, "replace", capture_replace)
    resolve_seed_drafts(tmp_path, DraftClient())
    resolve_seed_drafts(tmp_path, DraftClient())

    assert len(sources) == 2
    assert sources[0] != sources[1]
    assert all(path.parent == seed_dir for path in sources)
