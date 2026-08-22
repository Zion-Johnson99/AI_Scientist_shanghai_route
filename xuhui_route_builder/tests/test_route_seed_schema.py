import json
from datetime import date
from pathlib import Path

import pytest

from xuhui_route_builder.routes import load_route_seeds


def test_route_seed_file_contains_90_unique_routes() -> None:
    seed_path = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seeds.json"
    seeds = load_route_seeds(seed_path)

    assert len(seeds) == 90
    assert len({seed.seed_id for seed in seeds}) == 90
    assert all(seed.source_url.startswith("https://") for seed in seeds)
    assert all(seed.confidence in {"高", "中高", "中", "中低"} for seed in seeds)
    assert all(date(2026, 8, 15) <= seed.source_accessed_at <= date.today() for seed in seeds)


def test_route_seed_json_is_plain_list() -> None:
    seed_path = Path(__file__).resolve().parents[1] / "data" / "seeds" / "route_seeds.json"
    raw = json.loads(seed_path.read_text(encoding="utf-8"))

    assert isinstance(raw, list)
    assert {"seed_id", "route_name", "route_mode", "source_url"}.issubset(raw[0])


def test_route_seed_loader_uses_type_error_for_non_list_payload(tmp_path: Path) -> None:
    source = tmp_path / "route_seeds.json"
    source.write_text("{}", encoding="utf-8")

    with pytest.raises(TypeError, match=r"route_seeds\.json must be a list"):
        load_route_seeds(source)
