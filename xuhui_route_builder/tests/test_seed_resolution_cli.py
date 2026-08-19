import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

import xuhui_route_builder.cli as cli_module
from xuhui_route_builder.cli import resolve_seed_drafts, validate_seeds
from xuhui_route_builder.routes import resolve_node_query


def _expanded_drafts() -> list[dict]:
    source = []
    research = Path(__file__).resolve().parents[1] / "data" / "seeds" / "research"
    for path in sorted(research.glob("*_route_candidates_0813.json")):
        source.extend(json.loads(path.read_text(encoding="utf-8")))
    if len(source) == 90:
        return source
    path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "seeds"
        / "route_seed_drafts.json"
    )
    source = json.loads(path.read_text(encoding="utf-8"))
    drafts = []
    for copy_index in range(6):
        for draft in source:
            item = deepcopy(draft)
            item["seed_id"] = f"{item['seed_id']}-{copy_index}"
            item["route_name"] = f"{item['route_name']}-{copy_index}"
            drafts.append(item)
    return drafts


def _write_expanded_drafts(seed_dir: Path) -> list[dict]:
    drafts = _expanded_drafts()
    (seed_dir / "route_seed_drafts.json").write_text(
        json.dumps(drafts, ensure_ascii=False), encoding="utf-8"
    )
    return drafts


class DraftClient:
    def __init__(self, fail_query: str | None = None) -> None:
        self.fail_query = fail_query
        self.calls: list[tuple[str, str]] = []

    def place_text_v5(self, query: str, region: str = "310104"):
        self.calls.append((query, region))
        if query == self.fail_query:
            raise RuntimeError("forced failure")
        drafts_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "seeds"
            / "route_seed_drafts.json"
        )
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

    def geocode(self, address: str, city: str = "上海"):
        self.calls.append((address, city))
        if address == self.fail_query:
            raise RuntimeError("forced failure")
        return SimpleNamespace(
            status="1",
            raw_path=f"raw/{len(self.calls)}.json",
            payload={
                "geocodes": [
                    {
                        "formatted_address": address,
                        "adcode": "310104",
                        "location": f"121.{4000 + len(self.calls):04d},31.{1000 + len(self.calls):04d}",
                    }
                ]
            },
        )

    def resolve(self, expected_name, query, expected_poi_id, seed_id, node_index):
        return resolve_node_query(
            expected_name, query, self, expected_poi_id, seed_id, node_index
        )


def test_route_seed_drafts_have_exact_balanced_strict_schema() -> None:
    drafts = _expanded_drafts()

    assert len(drafts) == 90
    assert {
        mode: sum(item["route_mode"] == mode for item in drafts)
        for mode in ("run", "walk", "bike")
    } == {
        "run": 30,
        "walk": 30,
        "bike": 30,
    }
    for draft in drafts:
        assert draft["source_level"] in {"A", "B", "C"}
        assert draft["source_url"].startswith("https://")
        assert draft["source_accessed_at"] == "2026-08-13"
        assert draft["access_restrictions"]
        assert len(draft["nodes"]) >= 2
        for node in draft["nodes"]:
            assert set(node).issubset({"query", "expected_name", "expected_poi_id"})
            assert node["query"] and node["expected_name"]
            assert "lng_gcj02" not in node and "poi_id" not in node


def test_route_seed_drafts_do_not_use_out_of_district_lupu_bridge_poi() -> None:
    drafts = _expanded_drafts()

    assert all(
        node["expected_name"] != "卢浦大桥"
        for draft in drafts
        for node in draft["nodes"]
    )


def test_resolve_node_query_returns_strict_real_node_and_contextual_error() -> None:
    client = DraftClient()
    node, raw_path = resolve_node_query("入口", "入口", client, None, "seed-1", 2)

    assert node.poi_id == "REAL0001"
    assert node.lng_gcj02 is not None
    assert raw_path == "raw/1.json"
    assert client.calls == [("入口", "310104")]

    with pytest.raises(ValueError, match=r"seed_id=seed-1.*node_index=3.*坏入口"):
        resolve_node_query(
            "坏入口", "坏入口", DraftClient(fail_query="坏入口"), None, "seed-1", 3
        )


def test_repository_raw_paths_are_persisted_as_relative_paths(tmp_path: Path) -> None:
    raw_path = tmp_path / "data" / "raw" / "amap" / "walking_v2_test.json"

    assert (
        cli_module._portable_raw_path(tmp_path, str(raw_path))
        == "data/raw/amap/walking_v2_test.json"
    )


def test_resolve_seed_drafts_rejects_legacy_portfolio_without_new_gates(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    _write_expanded_drafts(seed_dir)

    with pytest.raises(ValueError, match="route seed portfolio failed"):
        resolve_seed_drafts(tmp_path, DraftClient())

    assert not (seed_dir / "route_seeds.json").exists()


def test_validate_seeds_accepts_balanced_portfolio(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seeds.json"
    target = tmp_path / "data" / "seeds" / "route_seeds.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())

    seeds = validate_seeds(tmp_path)

    assert len(seeds) == 90
    assert {
        mode: sum(seed.route_mode == mode for seed in seeds)
        for mode in ("walk", "run", "bike")
    } == {
        "walk": 30,
        "run": 30,
        "bike": 30,
    }
    assert all(
        seed.preference_hits == [] for seed in seeds if seed.route_mode == "walk"
    )
    assert all(len(seed.preference_search_status) == 4 for seed in seeds)
    assert {
        mode: sum(
            seed.route_mode == mode and seed.route_shape == "strict_loop"
            for seed in seeds
        )
        for mode in ("walk", "run", "bike")
    } == {"walk": 14, "run": 15, "bike": 15}


def test_resolve_seed_drafts_does_not_overwrite_on_failure(tmp_path: Path) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    drafts = _write_expanded_drafts(seed_dir)
    target = seed_dir / "route_seeds.json"
    target.write_text("old-content", encoding="utf-8")
    failing_query = drafts[2]["nodes"][1]["query"]

    with pytest.raises(ValueError):
        resolve_seed_drafts(tmp_path, DraftClient(fail_query=failing_query))

    assert target.read_text(encoding="utf-8") == "old-content"
    assert not (seed_dir / "route_seeds.json.tmp").exists()


def test_resolve_seed_drafts_reports_all_node_failures(tmp_path: Path) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    drafts = _write_expanded_drafts(seed_dir)
    first_query = drafts[0]["nodes"][0]["query"]
    second_query = drafts[1]["nodes"][0]["query"]

    class TwoFailureClient(DraftClient):
        def place_text_v5(self, query: str, region: str = "310104"):
            if query in {first_query, second_query}:
                raise RuntimeError(f"forced failure {query}")
            return super().place_text_v5(query, region)

    with pytest.raises(ValueError) as caught:
        resolve_seed_drafts(tmp_path, TwoFailureClient())

    assert first_query in str(caught.value)
    assert second_query in str(caught.value)


def test_validate_seeds_rejects_wrong_mode_counts_or_missing_restrictions(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    drafts = _expanded_drafts()
    drafts[0]["route_mode"] = "walk"
    drafts[0]["allowed_modes"] = ["walk"]
    drafts[1]["access_restrictions"] = []
    (seed_dir / "route_seed_drafts.json").write_text(
        json.dumps(drafts, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        resolve_seed_drafts(tmp_path, DraftClient())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda drafts: drafts[0].update({"unexpected": True}), "extra"),
        (lambda drafts: drafts[1].update({"seed_id": drafts[0]["seed_id"]}), "seed_id"),
        (
            lambda drafts: drafts[1].update({"route_name": drafts[0]["route_name"]}),
            "route_name",
        ),
        (lambda drafts: drafts[0].update({"source_name": ""}), "source_name"),
        (lambda drafts: drafts[0].update({"evidence_note": ""}), "evidence_note"),
        (lambda drafts: drafts[0].update({"allowed_modes": ["walk"]}), "allowed_modes"),
        (lambda drafts: drafts[0]["nodes"][0].update({"extra": "bad"}), "nodes"),
    ],
)
def test_draft_preflight_rejects_invalid_collection_before_api_calls(
    tmp_path: Path, mutate, message: str
) -> None:
    drafts = _expanded_drafts()
    mutate(drafts)
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "route_seed_drafts.json").write_text(
        json.dumps(drafts, ensure_ascii=False), encoding="utf-8"
    )
    client = DraftClient()

    with pytest.raises(ValueError, match=rf"draft index=.*seed_id=.*{message}"):
        resolve_seed_drafts(tmp_path, client)
    assert client.calls == []


def test_atomic_replace_failure_preserves_existing_target_and_cleans_temp(
    tmp_path: Path, monkeypatch
) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    _write_expanded_drafts(seed_dir)
    target = seed_dir / "route_seeds.json"
    target.write_text("old-content", encoding="utf-8")
    monkeypatch.setattr(cli_module, "_validate_seed_collection", lambda seeds: None)

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(cli_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        resolve_seed_drafts(tmp_path, DraftClient())

    assert target.read_text(encoding="utf-8") == "old-content"
    assert list(seed_dir.glob(".route_seeds.*.tmp")) == []


def test_atomic_write_failure_preserves_existing_target_and_cleans_temp(
    tmp_path: Path, monkeypatch
) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    _write_expanded_drafts(seed_dir)
    target = seed_dir / "route_seeds.json"
    target.write_text("old-content", encoding="utf-8")
    monkeypatch.setattr(cli_module, "_validate_seed_collection", lambda seeds: None)

    def fail_dump(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(cli_module.json, "dump", fail_dump)
    with pytest.raises(OSError, match="write failed"):
        resolve_seed_drafts(tmp_path, DraftClient())

    assert target.read_text(encoding="utf-8") == "old-content"
    assert list(seed_dir.glob(".route_seeds.*.tmp")) == []


def test_atomic_write_uses_a_unique_temp_name_for_each_run(
    tmp_path: Path, monkeypatch
) -> None:
    seed_dir = tmp_path / "data" / "seeds"
    seed_dir.mkdir(parents=True)
    _write_expanded_drafts(seed_dir)
    sources: list[Path] = []
    real_replace = cli_module.os.replace
    monkeypatch.setattr(cli_module, "_validate_seed_collection", lambda seeds: None)

    def capture_replace(source_path, target_path):
        sources.append(Path(source_path))
        real_replace(source_path, target_path)

    monkeypatch.setattr(cli_module.os, "replace", capture_replace)
    resolve_seed_drafts(tmp_path, DraftClient())
    resolve_seed_drafts(tmp_path, DraftClient())

    assert len(sources) == 2
    assert sources[0] != sources[1]
    assert all(path.parent == seed_dir for path in sources)
