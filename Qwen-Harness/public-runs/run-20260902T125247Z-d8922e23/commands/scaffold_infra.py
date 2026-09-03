"""Create the static infrastructure of the generated workspace.

Writes project skeletons, config, docs, launch scripts and the harness run copy.
Idempotent: existing files are overwritten with the canonical content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

RUN_DIR: Final[Path] = Path(__file__).resolve().parents[1]
SOURCE: Final[Path] = RUN_DIR / "workspace" / "source"
PUBLISH: Final[Path] = RUN_DIR / "publish"
RUN_ID: Final[str] = "run-20260902T125247Z-d8922e23"

FILES: dict[str, str] = {}


def add(relative: str, content: str) -> None:
    FILES[relative] = content


# ---------------------------------------------------------------- pyproject
add(
    "pyproject.toml",
    """[project]
name = "xuhui-healthy-route-round2"
version = "2.0.0"
description = "Independent round-2 build: Xuhui healthy route generation, environment exposure, deterministic recommendation and a fully offline local web product."
requires-python = ">=3.10"
dependencies = []

[tool.ruff]
line-length = 100
target-version = "py310"
extend-exclude = [
    "xuhui_route_builder/data",
    "web",
    "node",
    ".venv",
]

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "BLE", "RUF", "TRY"]
ignore = ["RUF001", "RUF002", "RUF003", "TRY003", "TRY301"]

[tool.ruff.lint.isort]
known-first-party = ["routes", "environment", "evaluation"]

[tool.pyright]
typeCheckingMode = "basic"
pythonVersion = "3.10"
extraPaths = ["."]
include = [
    "routes",
    "environment",
    "evaluation",
    "scripts",
    "tests",
    "xuhui_route_builder",
    "weather_api_data",
    "evaluation_model_qwen",
]
exclude = [
    "**/__pycache__",
    "**/node_modules",
    "xuhui_route_builder/data",
    "web",
    "node",
]
reportMissingImports = "error"
reportUnusedImport = "warning"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
filterwarnings = ["error::DeprecationWarning"]
""",
)

# ---------------------------------------------------------------- conftest
CONFTEST = '''"""Put the generated workspace root on sys.path for every test session."""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
'''
for project in ("xuhui_route_builder", "weather_api_data", "evaluation_model_qwen"):
    add(f"{project}/tests/conftest.py", CONFTEST)

add(
    "Qwen-Harness/tests/conftest.py",
    '''"""Put both the harness copy and the generated workspace root on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COPY_ROOT = HERE.parent
SOURCE_ROOT = COPY_ROOT.parent
for candidate in (str(SOURCE_ROOT), str(COPY_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
''',
)

# ---------------------------------------------------------------- project packages
add(
    "xuhui_route_builder/__init__.py",
    '''"""Route module root: 90 accepted Xuhui walk / run / bike routes."""

from __future__ import annotations

from pathlib import Path

MODULE_ROOT: Path = Path(__file__).resolve().parent
DATA_WEB: Path = MODULE_ROOT / "data" / "web"
ROUTE_CATALOG_RELATIVE: str = "data/web/route_catalog.json"
ROUTES_GEOJSON_RELATIVE: str = "data/web/xuhui_routes.geojson"
BOUNDARY_GEOJSON_RELATIVE: str = "data/web/xuhui_boundary.geojson"
ENTRIES_GEOJSON_RELATIVE: str = "data/web/xuhui_entries.geojson"
POI_CATALOG_RELATIVE: str = "data/web/poi_catalog.json"
ACCESS_CASES_RELATIVE: str = "data/web/access_cases.json"
ENVIRONMENT_DASHBOARD_RELATIVE: str = "data/web/environment_dashboard.json"

__all__ = [
    "ACCESS_CASES_RELATIVE",
    "BOUNDARY_GEOJSON_RELATIVE",
    "DATA_WEB",
    "ENTRIES_GEOJSON_RELATIVE",
    "ENVIRONMENT_DASHBOARD_RELATIVE",
    "MODULE_ROOT",
    "POI_CATALOG_RELATIVE",
    "ROUTE_CATALOG_RELATIVE",
    "ROUTES_GEOJSON_RELATIVE",
]
''',
)

add(
    "xuhui_route_builder/route_builder.py",
    '''"""Adapter surface over the generated route artifacts.

Reads only files produced inside this run; performs no network access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODULE_ROOT: Path = Path(__file__).resolve().parent
CORE_PAIR: tuple[str, str] = ("data/web/route_catalog.json", "data/web/xuhui_routes.geojson")
OPTIONAL_ARTIFACTS: tuple[str, ...] = (
    "data/web/xuhui_entries.geojson",
    "data/web/poi_catalog.json",
    "data/web/access_cases.json",
)


class RouteArtifactError(RuntimeError):
    """Raised when a core route artifact is missing or unreadable."""


@dataclass(frozen=True)
class RouteModuleResult:
    """Immutable summary of the route module artifacts."""

    route_count: int
    mode_counts: dict[str, int]
    kind_counts: dict[str, dict[str, int]]
    bucket_counts: dict[str, int]
    area_counts: dict[str, int]
    accepted_count: int
    needs_review_count: int
    crs: str
    route_ids: tuple[str, ...]
    artifacts: dict[str, int]
    missing_artifacts: tuple[str, ...]


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise RouteArtifactError(f"路线产物缺失: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RouteArtifactError(f"路线产物无法解析: {path.name}") from exc


def load_catalog(root: Path | None = None) -> dict[str, Any]:
    """Return the route catalog payload, raising if the core pair is absent."""
    base = root or MODULE_ROOT
    for relative in CORE_PAIR:
        if not (base / relative).is_file():
            raise RouteArtifactError("核心路线产物缺失（route_catalog.json / xuhui_routes.geojson）")
    payload = _read_json(base / CORE_PAIR[0])
    if not isinstance(payload, dict):
        raise RouteArtifactError("route_catalog.json 顶层不是对象")
    return payload


def load_routes_geojson(root: Path | None = None) -> dict[str, Any]:
    """Return the route FeatureCollection."""
    base = root or MODULE_ROOT
    payload = _read_json(base / CORE_PAIR[1])
    if not isinstance(payload, dict):
        raise RouteArtifactError("xuhui_routes.geojson 顶层不是对象")
    return payload


def build_result(root: Path | None = None) -> RouteModuleResult:
    """Summarise the artifacts and report which optional files are absent."""
    base = root or MODULE_ROOT
    catalog = load_catalog(base)
    routes: list[dict[str, Any]] = list(catalog.get("routes") or [])
    artifacts: dict[str, int] = {}
    for relative in (*CORE_PAIR, *OPTIONAL_ARTIFACTS):
        target = base / relative
        artifacts[relative] = target.stat().st_size if target.is_file() else 0
    missing = tuple(
        relative for relative in OPTIONAL_ARTIFACTS if not (base / relative).is_file()
    )
    accepted = sum(1 for item in routes if item.get("status") == "accepted")
    return RouteModuleResult(
        route_count=int(catalog.get("route_count") or len(routes)),
        mode_counts=dict(catalog.get("mode_counts") or {}),
        kind_counts={k: dict(v) for k, v in (catalog.get("kind_counts") or {}).items()},
        bucket_counts=dict(catalog.get("bucket_counts") or {}),
        area_counts=dict(catalog.get("area_counts") or {}),
        accepted_count=accepted,
        needs_review_count=sum(1 for item in routes if item.get("status") == "needs_review"),
        crs=str(catalog.get("crs") or "unknown"),
        route_ids=tuple(str(item.get("route_id")) for item in routes),
        artifacts=artifacts,
        missing_artifacts=missing,
    )


def as_dict(result: RouteModuleResult) -> dict[str, Any]:
    """Serialise a RouteModuleResult for JSON output."""
    return {
        "route_count": result.route_count,
        "mode_counts": result.mode_counts,
        "kind_counts": result.kind_counts,
        "bucket_counts": result.bucket_counts,
        "area_counts": result.area_counts,
        "accepted_count": result.accepted_count,
        "needs_review_count": result.needs_review_count,
        "crs": result.crs,
        "route_id_count": len(result.route_ids),
        "artifacts": result.artifacts,
        "missing_artifacts": list(result.missing_artifacts),
    }
''',
)

add(
    "weather_api_data/__init__.py",
    '''"""Environment data project root for the 54-cell Xuhui exposure grid."""

from __future__ import annotations

from pathlib import Path

MODULE_ROOT: Path = Path(__file__).resolve().parent
GRID_ROWS: int = 6
GRID_COLS: int = 9
GRID_CELL_COUNT: int = GRID_ROWS * GRID_COLS
CANONICAL_CRS: str = "CRS84/WGS84 (lon,lat)"

__all__ = ["CANONICAL_CRS", "GRID_CELL_COUNT", "GRID_COLS", "GRID_ROWS", "MODULE_ROOT"]
''',
)

add(
    "weather_api_data/environment_data.py",
    '''"""Adapter surface over the generated environment dashboard.

The dashboard lives beside the route artifacts because the harness environment
adapter resolves it relative to the route module root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DASHBOARD_RELATIVE: str = "data/web/environment_dashboard.json"
STATUS_DOMAIN: frozenset[str] = frozenset({"measured", "derived", "estimated", "unavailable"})
GRID_CELL_COUNT: int = 54
MISSING_RATE_MAX: float = 0.10
CANONICAL_CRS: str = "CRS84/WGS84 (lon,lat)"


class EnvironmentArtifactError(RuntimeError):
    """Raised when the dashboard is missing or structurally invalid."""


@dataclass(frozen=True)
class EnvironmentModuleResult:
    """Immutable summary of the environment dashboard contract."""

    cell_count: int
    route_count: int
    field_keys: tuple[str, ...]
    missing_rate: dict[str, float]
    worst_missing_rate: float
    unit_mismatches: int
    status_violations: int
    crs: str
    data_generated_at: str
    excluded_fields: tuple[str, ...]
    passed: bool
    errors: tuple[str, ...]


def route_module_root() -> Path:
    """Return the route module root, which owns the dashboard file."""
    return Path(__file__).resolve().parent.parent / "xuhui_route_builder"


def load_dashboard(root: Path | None = None) -> dict[str, Any]:
    """Return the dashboard payload, raising if it is absent."""
    base = root or route_module_root()
    target = base / DASHBOARD_RELATIVE
    if not target.is_file():
        raise EnvironmentArtifactError(f"环境产物缺失: {DASHBOARD_RELATIVE}")
    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise EnvironmentArtifactError("environment_dashboard.json 无法解析") from exc
    if not isinstance(payload, dict):
        raise EnvironmentArtifactError("environment_dashboard.json 顶层不是对象")
    return payload


def audit(payload: dict[str, Any]) -> EnvironmentModuleResult:
    """Check cell count, units, status domain, CRS and per-field missing rate."""
    errors: list[str] = []
    cells: list[dict[str, Any]] = list(payload.get("cells") or [])
    routes: list[dict[str, Any]] = list(payload.get("routes") or [])
    specs: list[dict[str, Any]] = list(payload.get("field_specs") or [])
    canonical: dict[str, str] = {str(s.get("key")): str(s.get("unit")) for s in specs}
    if len(cells) != GRID_CELL_COUNT:
        errors.append("cell_count_mismatch")
    crs = str(payload.get("crs") or "")
    if crs != CANONICAL_CRS:
        errors.append("crs_mismatch")
    unit_mismatches = 0
    status_violations = 0
    for cell in cells:
        values = cell.get("values")
        if not isinstance(values, dict):
            errors.append("cell_values_missing")
            continue
        for key, block in values.items():
            if not isinstance(block, dict):
                errors.append("value_block_not_object")
                continue
            expected = canonical.get(str(key))
            if expected is not None and str(block.get("unit")) != expected:
                unit_mismatches += 1
            if str(block.get("status")) not in STATUS_DOMAIN:
                status_violations += 1
    if unit_mismatches:
        errors.append("unit_mismatch")
    if status_violations:
        errors.append("status_out_of_domain")
    rates_raw = payload.get("missing_rate")
    missing_rate: dict[str, float] = (
        {str(k): float(v) for k, v in rates_raw.items()} if isinstance(rates_raw, dict) else {}
    )
    worst = max(missing_rate.values()) if missing_rate else 0.0
    if worst > MISSING_RATE_MAX:
        errors.append("missing_rate_exceeded")
    excluded = tuple(
        str(item.get("key"))
        for item in (payload.get("excluded_fields") or [])
        if isinstance(item, dict)
    )
    return EnvironmentModuleResult(
        cell_count=len(cells),
        route_count=len(routes),
        field_keys=tuple(canonical),
        missing_rate=missing_rate,
        worst_missing_rate=worst,
        unit_mismatches=unit_mismatches,
        status_violations=status_violations,
        crs=crs,
        data_generated_at=str(payload.get("data_generated_at") or "unknown"),
        excluded_fields=excluded,
        passed=not errors,
        errors=tuple(errors),
    )


def as_dict(result: EnvironmentModuleResult) -> dict[str, Any]:
    """Serialise an EnvironmentModuleResult for JSON output."""
    return {
        "cell_count": result.cell_count,
        "route_count": result.route_count,
        "field_count": len(result.field_keys),
        "field_keys": list(result.field_keys),
        "missing_rate": result.missing_rate,
        "worst_missing_rate": result.worst_missing_rate,
        "unit_mismatches": result.unit_mismatches,
        "status_violations": result.status_violations,
        "crs": result.crs,
        "data_generated_at": result.data_generated_at,
        "excluded_fields": list(result.excluded_fields),
        "passed": result.passed,
        "errors": list(result.errors),
    }
''',
)

add(
    "evaluation_model_qwen/__init__.py",
    '''"""Deterministic five-dimension recommendation and evaluation project root."""

from __future__ import annotations

from pathlib import Path

MODULE_ROOT: Path = Path(__file__).resolve().parent
WEIGHTS_RELATIVE: str = "config/default_weights.json"
DIMENSIONS: tuple[str, ...] = (
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "user_preference",
)

__all__ = ["DIMENSIONS", "MODULE_ROOT", "WEIGHTS_RELATIVE"]
''',
)

add(
    "web_product.py",
    '''"""Web adapter surface: resolves the published local product and its payload."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parent
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
PAYLOAD_RELATIVE: str = "publish/research_harness_latest.json"
INDEX_RELATIVE: str = "index.html"
PRODUCT_RELATIVE: str = "publish/local-product"
REQUIRED_PAYLOAD_KEYS: tuple[str, ...] = (
    "run_id",
    "generated_at",
    "status",
    "research_question",
    "hypothesis",
)


class WebProductError(RuntimeError):
    """Raised when the published web product or its payload is unusable."""


@dataclass(frozen=True)
class WebProductResult:
    """Immutable summary of the published local web product."""

    payload_path: str
    index_path: str
    payload_present: bool
    index_present: bool
    asset_count: int
    total_bytes: int
    missing_payload_keys: tuple[str, ...]
    external_references: tuple[str, ...]
    passed: bool
    errors: tuple[str, ...]


def payload_path(root: Path | None = None) -> Path:
    """Return the run-relative research payload path."""
    return (root or RUN_ROOT) / PAYLOAD_RELATIVE


def product_root(root: Path | None = None) -> Path:
    """Return the published local product directory."""
    return (root or RUN_ROOT) / PRODUCT_RELATIVE


def _external_references(index: Path) -> tuple[str, ...]:
    if not index.is_file():
        return ()
    text = index.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for marker in ("<script src=", "<link href=", "<img src=", "@import"):
        position = 0
        while True:
            found = text.find(marker, position)
            if found < 0:
                break
            snippet = text[found : found + len(marker) + 120]
            if "http://" in snippet or "https://" in snippet or "//" in snippet.split('"')[-1]:
                quote = snippet.split(marker, 1)[1].strip().lstrip("=").strip()
                if quote.startswith(("http://", "https://", "//")):
                    hits.append(marker.strip())
            position = found + len(marker)
    return tuple(sorted(set(hits)))


def audit(root: Path | None = None) -> WebProductResult:
    """Check the payload keys, the index file and offline-only asset references."""
    base = root or RUN_ROOT
    payload = payload_path(base)
    product = product_root(base)
    index = product / INDEX_RELATIVE
    errors: list[str] = []
    missing_keys: list[str] = []
    if payload.is_file():
        try:
            with payload.open("r", encoding="utf-8") as handle:
                data: Any = json.load(handle)
        except json.JSONDecodeError as exc:
            raise WebProductError("research_harness_latest.json 无法解析") from exc
        if not isinstance(data, dict):
            errors.append("payload_not_object")
        else:
            missing_keys = [k for k in REQUIRED_PAYLOAD_KEYS if not data.get(k)]
            if missing_keys:
                errors.append("payload_required_key_missing")
    else:
        errors.append("payload_missing")
    if not index.is_file():
        errors.append("index_missing")
    assets = sorted(p for p in product.rglob("*") if p.is_file())
    external = _external_references(index)
    if external:
        errors.append("external_asset_reference")
    return WebProductResult(
        payload_path=str(payload.relative_to(base)) if payload.is_relative_to(base) else payload.name,
        index_path=str(index.relative_to(product)) if index.is_file() else INDEX_RELATIVE,
        payload_present=payload.is_file(),
        index_present=index.is_file(),
        asset_count=len(assets),
        total_bytes=sum(p.stat().st_size for p in assets),
        missing_payload_keys=tuple(missing_keys),
        external_references=external,
        passed=not errors,
        errors=tuple(errors),
    )


def as_dict(result: WebProductResult) -> dict[str, Any]:
    """Serialise a WebProductResult for JSON output."""
    return {
        "payload_path": result.payload_path,
        "index_path": result.index_path,
        "payload_present": result.payload_present,
        "index_present": result.index_present,
        "asset_count": result.asset_count,
        "total_bytes": result.total_bytes,
        "missing_payload_keys": list(result.missing_payload_keys),
        "external_references": list(result.external_references),
        "passed": result.passed,
        "errors": list(result.errors),
    }
''',
)

# ---------------------------------------------------------------- tests
add(
    "xuhui_route_builder/tests/test_route_artifacts.py",
    '''"""Contract tests for the generated route artifacts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from xuhui_route_builder import route_builder

ROUTE_ID_PATTERN = re.compile(r"^XH_(WALK|RUN|BIKE)_\\d{4}$")
LON_RANGE = (121.30, 121.55)
LAT_RANGE = (31.05, 31.30)
CANONICAL_CRS = "CRS84/WGS84 (lon,lat)"


@pytest.fixture(scope="module")
def result() -> route_builder.RouteModuleResult:
    return route_builder.build_result()


def test_core_artifacts_present(result: route_builder.RouteModuleResult) -> None:
    assert result.route_count > 0
    assert result.artifacts["data/web/route_catalog.json"] > 0
    assert result.artifacts["data/web/xuhui_routes.geojson"] > 0


def test_portfolio_composition(result: route_builder.RouteModuleResult) -> None:
    assert result.route_count == 90
    assert result.mode_counts == {"walk": 30, "run": 30, "bike": 30}
    assert result.accepted_count == 90
    assert result.needs_review_count == 0
    for mode, kinds in result.kind_counts.items():
        assert 14 <= kinds.get("strict_loop", 0) <= 16, mode
        assert kinds.get("strict_loop", 0) + kinds.get("one_way", 0) == 30, mode


def test_area_coverage(result: route_builder.RouteModuleResult) -> None:
    expected = {
        "west_bund",
        "longhua",
        "xujiahui",
        "hengfu",
        "shanghai_botanical_garden",
        "kangjian",
        "caohejing",
        "huajing",
    }
    assert expected <= set(result.area_counts)
    assert all(count >= 1 for count in result.area_counts.values())


def test_distance_band_counts(result: route_builder.RouteModuleResult) -> None:
    per_mode: dict[str, int] = {}
    for key, count in result.bucket_counts.items():
        mode = key.split(":", 1)[0] if ":" in key else key
        per_mode[mode] = per_mode.get(mode, 0) + count
        assert count == 10, key
    assert sorted(per_mode.values()) == [30, 30, 30]


def test_route_ids_unique_and_wellformed(result: route_builder.RouteModuleResult) -> None:
    ids = list(result.route_ids)
    assert len(ids) == len(set(ids))
    for route_id in ids:
        assert ROUTE_ID_PATTERN.match(route_id), route_id


def test_crs_declaration(result: route_builder.RouteModuleResult) -> None:
    assert result.crs == CANONICAL_CRS


def test_geojson_coordinates_in_district_bbox() -> None:
    payload = route_builder.load_routes_geojson()
    features = list(payload.get("features") or [])
    assert len(features) == 90
    catalog_ids = set(route_builder.build_result().route_ids)
    seen: set[str] = set()
    for feature in features:
        properties = feature.get("properties") or {}
        route_id = str(properties.get("route_id"))
        seen.add(route_id)
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        assert len(coords) >= 2, route_id
        for lon, lat in coords:
            assert LON_RANGE[0] <= float(lon) <= LON_RANGE[1], route_id
            assert LAT_RANGE[0] <= float(lat) <= LAT_RANGE[1], route_id
    assert seen == catalog_ids


def test_boundary_ring_closed_and_large() -> None:
    root = route_builder.MODULE_ROOT
    target: Path = root / route_builder.BOUNDARY_GEOJSON_RELATIVE
    assert target.is_file()
    payload = route_builder._read_json(target)
    ring = payload["features"][0]["geometry"]["coordinates"][0]
    assert len(ring) >= 100
    assert ring[0] == ring[-1]
''',
)

add(
    "weather_api_data/tests/test_environment_contract.py",
    '''"""Contract tests for the 54-cell environment dashboard."""

from __future__ import annotations

import pytest

from weather_api_data import environment_data


@pytest.fixture(scope="module")
def payload() -> dict:
    return environment_data.load_dashboard()


@pytest.fixture(scope="module")
def audit(payload: dict) -> environment_data.EnvironmentModuleResult:
    return environment_data.audit(payload)


def test_grid_cell_count(audit: environment_data.EnvironmentModuleResult) -> None:
    assert audit.cell_count == 54


def test_route_join(audit: environment_data.EnvironmentModuleResult) -> None:
    assert audit.route_count == 90


def test_crs_canonical(audit: environment_data.EnvironmentModuleResult) -> None:
    assert audit.crs == environment_data.CANONICAL_CRS


def test_units_canonical(audit: environment_data.EnvironmentModuleResult) -> None:
    assert audit.unit_mismatches == 0


def test_status_domain(audit: environment_data.EnvironmentModuleResult) -> None:
    assert audit.status_violations == 0


def test_missing_rate_within_budget(audit: environment_data.EnvironmentModuleResult) -> None:
    assert audit.worst_missing_rate <= environment_data.MISSING_RATE_MAX


def test_route_ids_resolve(payload: dict) -> None:
    from xuhui_route_builder import route_builder

    catalog_ids = set(route_builder.build_result().route_ids)
    cell_ids = {str(cell.get("cell_id")) for cell in payload.get("cells") or []}
    for entry in payload.get("routes") or []:
        assert str(entry.get("route_id")) in catalog_ids
        ids = entry.get("cell_ids") or []
        assert ids
        assert all(str(cid) in cell_ids for cid in ids)


def test_overall_contract(audit: environment_data.EnvironmentModuleResult) -> None:
    assert audit.passed, audit.errors
''',
)

add(
    "evaluation_model_qwen/tests/test_evaluation_contract.py",
    '''"""Contract tests for weights, recommendation and the experiment matrix."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation_model_qwen import DIMENSIONS, MODULE_ROOT, WEIGHTS_RELATIVE


def load_weights_file() -> dict:
    target: Path = MODULE_ROOT / WEIGHTS_RELATIVE
    assert target.is_file(), WEIGHTS_RELATIVE
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_weights_file_shape() -> None:
    payload = load_weights_file()
    weights = payload.get("weights") if isinstance(payload.get("weights"), dict) else payload
    assert set(weights) == set(DIMENSIONS)
    assert all(float(v) > 0.0 for v in weights.values())
    assert abs(sum(float(v) for v in weights.values()) - 1.0) < 1e-6


def test_scorer_renormalises_missing_dimensions() -> None:
    from evaluation import scorer

    present = {
        "environment_health": None,
        "sport_match": 80.0,
        "access_convenience": 60.0,
        "route_quality": 70.0,
        "user_preference": 50.0,
    }
    weights = {
        "environment_health": 0.30,
        "sport_match": 0.20,
        "access_convenience": 0.15,
        "route_quality": 0.20,
        "user_preference": 0.15,
    }
    total, effective = scorer.combine(present, weights)
    assert effective["environment_health"] == 0.0
    assert abs(sum(effective.values()) - 1.0) < 1e-9
    assert 0.0 <= total <= 100.0


def test_recommend_accepts_offline_kwarg() -> None:
    from evaluation import recommend as recommend_module

    signature_params = recommend_module.recommend.__code__.co_varnames
    assert "offline" in signature_params


def test_recommend_returns_empty_reason_not_raise() -> None:
    from evaluation import recommend as recommend_module

    catalog = {"routes": []}
    dashboard = {"cells": [], "routes": [], "field_specs": [], "risk_thresholds": {}}
    response = recommend_module.recommend(
        {"sport": "walk"},
        catalog,
        dashboard,
        [],
        {"entries": [], "parks": [], "services": []},
        {
            "environment_health": 0.30,
            "sport_match": 0.20,
            "access_convenience": 0.15,
            "route_quality": 0.20,
            "user_preference": 0.15,
        },
        offline=True,
    )
    assert response["candidate_count"] == 0
    assert response["empty_reason"]
    assert response["offline"] is True
    assert response["weights_sha256"]
''',
)

add(
    "Qwen-Harness/tests/test_run_copy.py",
    '''"""Tests for the offline harness run copy and its manifest."""

from __future__ import annotations

import json
from pathlib import Path

COPY_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = COPY_ROOT.parent.parent


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert isinstance(payload, dict)
    return payload


def test_run_copy_manifest_present() -> None:
    manifest = read_json(COPY_ROOT / "run_copy_manifest.json")
    assert manifest["source_run_id"] == RUN_ROOT.name
    assert manifest["offline"] is True
    assert manifest["dashscope_api_used"] is False
    assert manifest["provider"] == "qoder_session"
    assert manifest["model_name"] == "qwen3.8-max"
    assert manifest["billing_channel"] == "qoder_credits"
    assert isinstance(manifest["copied_files"], list)


def test_copied_files_exist_and_hash_matches() -> None:
    manifest = read_json(COPY_ROOT / "run_copy_manifest.json")
    for entry in manifest["copied_files"]:
        target = COPY_ROOT / entry["relative_path"]
        assert target.is_file(), entry["relative_path"]
        assert target.stat().st_size == entry["bytes"]
        digest = __import__("hashlib").sha256(target.read_bytes()).hexdigest()
        assert digest == entry["sha256"], entry["relative_path"]


def test_reproduce_entry_declares_no_network() -> None:
    text = (COPY_ROOT / "reproduce_harness.py").read_text(encoding="utf-8")
    assert "QwenModelClient" not in text
    assert "dashscope" not in text.lower()
    assert "from_env" not in text


def test_run_manifest_provider_channel() -> None:
    manifest = read_json(RUN_ROOT / "run_manifest.json")
    assert manifest["provider"] == "qoder_session"
    assert manifest["model_name"] == "qwen3.8-max"
    assert manifest["dashscope_api_used"] is False
''',
)

# ---------------------------------------------------------------- docs
add(
    "README.md",
    f"""# 徐汇健康路线 · 第二轮独立工程

本目录是 Qwen-Harness 第二轮实验（`{RUN_ID}`）中从零构建的独立工程副本，
不引用仓库现有 `xuhui_route_builder`、`weather_api_data`、`evaluation_model_qwen`
的任何实现、数据或页面代码。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `routes/` | 路网图构建、闭环与单程搜索、几何度量、质量门禁、路线目录产物 |
| `environment/` | 54 格环境网格、公开气象与空气质量接入、路线暴露聚合、契约校验 |
| `evaluation/` | 五维打分、确定性推荐、两条基线、实验矩阵指标、本地评价 API |
| `xuhui_route_builder/` | 路线模块根，`data/web/` 存放路线与环境产物 |
| `weather_api_data/` | 环境数据项目根与适配器 |
| `evaluation_model_qwen/` | 评价项目根，`config/default_weights.json` 为默认权重 |
| `web/` | 完整本地网页产品，零外部依赖 |
| `scripts/` | 生成、质量门禁、本地服务、浏览器验收脚本 |
| `tests/` | 跨模块集成测试 |
| `node/` | Node 契约测试 |
| `harness_copy/` | Qwen-Harness 运行副本与离线复现入口 |

## 复现

```powershell
cd workspace/source
python reproduce.py --stage all
```

分阶段：`--stage routes|environment|evaluation|web|checks`。

## 本地网页

```powershell
pwsh ../../publish/launch-local.ps1
```

或手动：

```powershell
cd ../../publish/local-product
python -m http.server 8765
```

浏览器打开 <http://127.0.0.1:8765/index.html>。

## 边界

- 全部计算离线、确定性，无随机数、无付费大模型调用。
- 公开数据来源、访问时间、用途与许可记录在 `../../sources/source_registry.jsonl`。
- 环境噪声为确定性代理量（`dB_proxy`），不是实测声级。
- 接驳时间为直线距离乘 1.35 绕行系数的估算，未调用任何在线路径规划接口。
""",
)

add(
    "docs/data_provenance.md",
    """# 数据来源与加工口径

## 原始公开数据

| 数据 | 来源 | 获取方式 | 许可 | 用途 |
| --- | --- | --- | --- | --- |
| 徐汇区行政边界 | OpenStreetMap relation 1278188（`boundary=administrative`, `admin_level=6`, `name:zh=徐汇区`） | Overpass API 关系查询 | ODbL 1.0 | 区内比例、网格范围、地图首屏 |
| 道路网 | OpenStreetMap `highway=*` way | 官方 OSM API `/api/0.6/map?bbox=` 6×6 网格切片，超限自动细分 | ODbL 1.0 | 路网图、路线搜索、道路贴合 |
| POI（公园、入口、服务设施） | OpenStreetMap node/way 标签 | 同上 | ODbL 1.0 | 区域锚点、入口池、邻近服务 |
| 气象 | Open-Meteo Forecast API（免密钥） | `urllib` 直连，落盘为 `sources/open_meteo_forecast.json` | CC BY 4.0 | 温度、体感、湿度、风速、阵风、降水 |
| 空气质量 | Open-Meteo Air Quality API（免密钥） | `urllib` 直连，落盘为 `sources/open_meteo_air_quality.json` | CC BY 4.0 | PM2.5、US AQI |

逐条来源、URL、访问时间、用途与许可见 `../../sources/source_registry.jsonl`。

## 加工层级标注

每个产物字段都带 `provenance` 与 `status`，取值含义固定：

| provenance | 含义 |
| --- | --- |
| `public_osm_data_fetched_in_this_run` | 本次运行内抓取的 OSM 原始数据 |
| `public_api_measurement` | 免密钥公开 API 返回的观测/预报值 |
| `deterministic_computation` | 由上述原始数据确定性计算得出 |
| `deterministic_proxy_model` | 确定性代理模型，非实测 |
| `manual_setting` | 人工设定的常量或阈值 |
| `qoder_judgement` | 由 Qoder 会话作出的判断，非数据 |

| status | 含义 | 可靠度乘子 |
| --- | --- | --- |
| `measured` | 来自公开 API 的真实数值 | 1.00 |
| `derived` | 由原始数据确定性推导 | 0.90 |
| `estimated` | 代理模型估算 | 0.75 |
| `unavailable` | 缺失，值必须为 `null` | 不计入 |

## 明确不是实测的量

- `noise_proxy_db`：由主干道密度与路网密度经固定公式映射到 35–85 的代理量，单位写作 `dB_proxy` 以区别于实测声级。徐汇区无可公开下载的分时段实测噪声栅格，因此不声称实测。
- `traffic_exposure_0_1`：主干道密度的固定尺度归一化，代理量。
- `estimated_access_min`：直线距离 × 1.35 绕行系数 ÷ 4.8 km/h。未调用任何在线路径规划接口，`api_distance_provenance` 固定为 `not_applicable_no_credentials`。
- 速度常量 `walk 4.8 / run 9.0 / bike 18.0 km/h` 为 `manual_setting`。

## 缺失值口径

缺失一律写 JSON `null`，禁止用 0、-1、中位数或插值填充。
每个字段在 `environment_dashboard.json.missing_rate` 中给出缺失率，阈值 ≤ 0.10。
公开 API 未覆盖的字段进入 `excluded_fields` 并写明原因，不进入打分。
""",
)

add(
    "docs/licence.md",
    """# 许可与署名

## OpenStreetMap（ODbL 1.0）

边界、路网、POI 均来自 OpenStreetMap 贡献者，采用 Open Database License 1.0。

按 ODbL 要求署名：

> 地图数据 © OpenStreetMap contributors, ODbL 1.0.
> https://www.openstreetmap.org/copyright

本目录内的产物为对 OSM 数据的加工结果（衍生数据库）。
分发时需保留本署名，并以 ODbL 1.0 或兼容条款共享衍生数据库。
未使用任何 OSM 官方瓦片服务或第三方瓦片 CDN。

## Open-Meteo（CC BY 4.0）

气象与空气质量数值来自 Open-Meteo 免费接口，采用 CC BY 4.0。

> Weather and air quality data by Open-Meteo.com, CC BY 4.0.
> https://open-meteo.com/en/terms

原始响应逐字保存在 `../../sources/open_meteo_forecast.json` 与
`../../sources/open_meteo_air_quality.json`，含抓取时间与请求 URL。

## 原创部分

`routes/`、`environment/`、`evaluation/`、`web/`、`scripts/`、`tests/`、`node/`
的全部代码、视觉设计、文案与交互结构为本次运行原创，
未复制仓库现有业务模块、第一轮生成源码或任何在线成品页面的
HTML、CSS、JavaScript、接口响应、GeoJSON 或静态资源。

## 未使用

- 无付费大模型 API 调用，无 DashScope / 百炼请求。
- 无商业地图密钥，无高德 / 百度 / Google Maps SDK。
- 无第三方前端库、字体或图标 CDN。
""",
)

add(
    "docs/reproduction.md",
    """# 复现说明

## 环境

- Python 3.11（3.10 起可用）
- Node.js 20+（本次运行使用 v24）
- 无需任何第三方 Python 包；标准库即可
- 无需任何 API 密钥

## 顺序

```powershell
cd workspace/source

# 1. 抓取公开原始数据（需要外网；已有 sources/ 时可跳过）
python ../../commands/fetch_osm4_api.py
python -m environment.fetch_public

# 2. 生成 90 条路线与全部路线产物
python reproduce.py --stage routes

# 3. 生成 54 格环境网格与路线暴露
python reproduce.py --stage environment

# 4. 打分、推荐、基线与实验矩阵
python reproduce.py --stage evaluation

# 5. 组装网页载荷与本地成品
python reproduce.py --stage web

# 6. 全部质量门禁与 checks/ 产物
python reproduce.py --stage checks
```

一次性执行：`python reproduce.py --stage all`。

## 确定性

- 不使用 `random`、不使用系统时钟参与计算。
- 所有时间戳由入口脚本一次性生成并作为参数向下传递。
- 相同 `sources/` 输入产生逐字节相同的产物（浮点统一 `round` 到固定位数）。

## 离线约束

复现全过程不得初始化任何大模型客户端，不得读取 `.env`。
`reproduce.py` 会在启动时断言 `DASHSCOPE_API_KEY` 与 `OPENAI_API_KEY`
未进入子进程环境，若存在则以清除后的环境重启自身。

## 验证

```powershell
cd workspace/source
uv run pytest Qwen-Harness/tests weather_api_data/tests evaluation_model_qwen/tests xuhui_route_builder/tests tests
uv run ruff check .
uv run pyright
cd node
node --test
```

## 本地网页

```powershell
pwsh ../../publish/launch-local.ps1
```

脚本在 `publish/local-product` 下启动 `python -m http.server`，
默认端口 8765，打印访问地址并保持前台运行。
""",
)

# ---------------------------------------------------------------- scripts
add(
    "scripts/__init__.py",
    '"""Run-local generation, quality-gate and serving scripts."""\n',
)

add(
    "scripts/serve_local.py",
    '''"""Serve the published local product over 127.0.0.1 with no external access."""

from __future__ import annotations

import argparse
import functools
import http.server
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
PRODUCT_ROOT: Path = RUN_ROOT / "publish" / "local-product"
DEFAULT_PORT: int = 8765
PROBE_PATHS: tuple[str, ...] = ("/index.html", "/styles.css", "/app.js", "/map.js")


class OfflineHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler bound to 127.0.0.1 that logs one line per request."""

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write("[serve] " + (format % args) + "\\n")
        sys.stdout.flush()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


def free_port(preferred: int) -> int:
    """Return the preferred port if free, otherwise an ephemeral one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as spare:
        spare.bind(("127.0.0.1", 0))
        return int(spare.getsockname()[1])


def probe(port: int) -> dict[str, int]:
    """Fetch the core assets once and return their status codes."""
    codes: dict[str, int] = {}
    for path in PROBE_PATHS:
        url = f"http://127.0.0.1:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                codes[path] = int(response.status)
        except OSError:
            codes[path] = 0
    return codes


def serve(port: int, open_browser: bool, background: bool) -> int:
    """Start the server; return a process exit code."""
    if not (PRODUCT_ROOT / "index.html").is_file():
        sys.stdout.write(f"[serve] 缺少 {PRODUCT_ROOT / 'index.html'}\\n")
        return 1
    handler = functools.partial(OfflineHandler, directory=str(PRODUCT_ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/index.html"
    sys.stdout.write(f"[serve] {url}\\n")
    sys.stdout.flush()
    if background:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        codes = probe(port)
        sys.stdout.write(f"[serve] probe={codes}\\n")
        server.shutdown()
        return 0 if all(code == 200 for code in codes.values()) else 1
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main() -> int:
    """Parse arguments and serve."""
    parser = argparse.ArgumentParser(description="Serve the run-local web product.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    port = free_port(args.port)
    return serve(port, not args.no_browser, args.probe_only)


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

add(
    "scripts/generate_all.py",
    '''"""Run every generation stage in order and report a per-stage status table."""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
STAGES: tuple[str, ...] = ("routes", "environment", "evaluation", "web", "checks")
SCRUBBED_ENV_KEYS: tuple[str, ...] = ("DASHSCOPE_API_KEY", "OPENAI_API_KEY")


def _scrubbed_env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV_KEYS}


def stage_routes(generated_at: str) -> dict[str, Any]:
    """Generate the 90-route portfolio and all route artifacts."""
    from routes import catalog, generator

    sources = RUN_ROOT / "sources"
    portfolio = generator.generate_portfolio(sources)
    import json

    pois_path = sources / "osm_xuhui_pois.json"
    with pois_path.open("r", encoding="utf-8") as handle:
        pois: Any = json.load(handle)
    out_dir = SOURCE_ROOT / "xuhui_route_builder" / "data" / "web"
    run_id = RUN_ROOT.name
    catalog.write_artifacts(portfolio, pois, out_dir, run_id, generated_at)
    return {
        "route_count": len(portfolio.routes),
        "kind_counts": portfolio.kind_counts,
        "accepted": portfolio.accepted_count,
    }


def stage_environment(generated_at: str) -> dict[str, Any]:
    """Build the 54-cell environment dashboard."""
    module = importlib.import_module("environment")
    builder: Callable[..., dict[str, Any]] = module.build_all
    return builder(generated_at)


def stage_evaluation(generated_at: str) -> dict[str, Any]:
    """Score, recommend, run baselines and export the experiment matrix."""
    module = importlib.import_module("evaluation")
    runner: Callable[..., dict[str, Any]] = module.run_all
    return runner(generated_at)


def stage_web(generated_at: str) -> dict[str, Any]:
    """Assemble the browser payload and the published local product."""
    result = subprocess.run(
        [sys.executable, str(SOURCE_ROOT / "scripts" / "build_web_payload.py"),
         "--generated-at", generated_at],
        cwd=str(SOURCE_ROOT),
        env=_scrubbed_env(),
        capture_output=True,
        text=True,
        timeout=900,
    )
    return {"exit_code": result.returncode, "stdout_tail": result.stdout[-800:]}


def stage_checks(generated_at: str) -> dict[str, Any]:
    """Run every quality gate and write the checks artifacts."""
    result = subprocess.run(
        [sys.executable, str(SOURCE_ROOT / "scripts" / "run_quality_gates.py"),
         "--generated-at", generated_at],
        cwd=str(SOURCE_ROOT),
        env=_scrubbed_env(),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    return {"exit_code": result.returncode, "stdout_tail": result.stdout[-1200:]}


HANDLERS: dict[str, Callable[[str], dict[str, Any]]] = {
    "routes": stage_routes,
    "environment": stage_environment,
    "evaluation": stage_evaluation,
    "web": stage_web,
    "checks": stage_checks,
}


def main() -> int:
    """Run the requested stages sequentially, printing a status table."""
    parser = argparse.ArgumentParser(description="Run all generation stages.")
    parser.add_argument("--stage", default="all", choices=("all", *STAGES))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated_at = args.generated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    selected = STAGES if args.stage == "all" else (args.stage,)
    failures = 0
    for name in selected:
        started = time.perf_counter()
        sys.stdout.write(f"== {name} ==\\n")
        sys.stdout.flush()
        try:
            summary = HANDLERS[name](generated_at)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            sys.stdout.write(f"   FAILED {type(exc).__name__}: {exc}\\n")
        else:
            code = summary.get("exit_code", 0) if isinstance(summary, dict) else 0
            if code:
                failures += 1
            sys.stdout.write(f"   ok {time.perf_counter() - started:.1f}s {summary}\\n")
        sys.stdout.flush()
    sys.stdout.write(f"STAGES_FAILED={failures}\\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

add(
    "reproduce.py",
    '''"""Single reproduction entry point for the generated workspace.

Guarantees no paid-LLM credential reaches any child process.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SOURCE_ROOT: Path = Path(__file__).resolve().parent
SCRIPT: Path = SOURCE_ROOT / "scripts" / "generate_all.py"
FORBIDDEN_ENV_KEYS: tuple[str, ...] = ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "BAILIAN_API_KEY")
STAGES: tuple[str, ...] = ("all", "routes", "environment", "evaluation", "web", "checks")


def clean_environment() -> dict[str, str]:
    """Return the process environment with every LLM credential removed."""
    return {key: value for key, value in os.environ.items() if key not in FORBIDDEN_ENV_KEYS}


def credentials_present() -> dict[str, bool]:
    """Report presence only, never values."""
    return {key: key in os.environ for key in FORBIDDEN_ENV_KEYS}


def main() -> int:
    """Dispatch to the stage runner with a scrubbed environment."""
    parser = argparse.ArgumentParser(description="Reproduce the round-2 build.")
    parser.add_argument("--stage", default="all", choices=STAGES)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    presence = credentials_present()
    sys.stdout.write(f"[reproduce] scrubbed_keys={sorted(k for k, v in presence.items() if v)}\\n")
    sys.stdout.write("[reproduce] provider=qoder_session model=qwen3.8-max online_llm=false\\n")
    sys.stdout.flush()
    generated_at = args.generated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    command = [sys.executable, str(SCRIPT), "--stage", args.stage, "--generated-at", generated_at]
    completed = subprocess.run(command, cwd=str(SOURCE_ROOT), env=clean_environment(), check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

# ---------------------------------------------------------------- harness copy
add(
    "Qwen-Harness/__init__.py",
    '"""Offline run copy of the Qwen-Harness workflow artifacts for this run."""\n',
)

add(
    "Qwen-Harness/reproduce_harness.py",
    '''"""Offline reproduction of the harness research stages for this run.

Reads only the artifacts already written inside this run directory and replays
the stage chain deterministically. It never constructs a model client and never
performs a network call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

COPY_ROOT: Path = Path(__file__).resolve().parent
RUN_ROOT: Path = COPY_ROOT.parent.parent
STAGES: tuple[str, ...] = (
    "initialize",
    "problem_framing",
    "source_collection",
    "evidence_extraction",
    "citation_validation",
    "gap_analysis",
    "hypothesis_generation",
    "hypothesis_critique",
    "hypothesis_selection",
    "experiment_design",
    "project_generation",
    "module_preflight",
    "module_execution",
    "experiment_analysis",
    "feedback_decision",
    "scientific_report",
    "web_payload",
    "final_validation",
    "publish_web",
)
STAGE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "initialize": ("run_manifest.json", "provider_manifest.json"),
    "problem_framing": ("experiments/research_goal.json",),
    "source_collection": ("sources/source_registry.jsonl",),
    "evidence_extraction": ("experiments/evidence_cards.jsonl",),
    "citation_validation": ("sources/source_registry.jsonl",),
    "gap_analysis": ("experiments/knowledge_gaps.json",),
    "hypothesis_generation": ("experiments/hypotheses.json",),
    "hypothesis_critique": ("experiments/hypothesis_critique.json",),
    "hypothesis_selection": ("experiments/hypotheses.json",),
    "experiment_design": (
        "experiments/experiment_design.json",
        "experiments/baseline_design.json",
        "experiments/evaluation_metrics.json",
        "experiments/stop_conditions.json",
    ),
    "project_generation": ("workspace/source/pyproject.toml",),
    "module_preflight": ("workspace/source/xuhui_route_builder/route_builder.py",),
    "module_execution": ("workspace/source/xuhui_route_builder/data/web/route_catalog.json",),
    "experiment_analysis": ("experiments/scientific_plan.json",),
    "feedback_decision": ("experiments/stop_conditions.json",),
    "scientific_report": ("reports/科学计划.md",),
    "web_payload": ("publish/research_harness_latest.json",),
    "final_validation": ("checks/generated_quality.json",),
    "publish_web": ("publish/local-product/index.html",),
}


def read_json(path: Path) -> Any:
    """Read a JSON file, returning None when it is absent."""
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay() -> dict[str, Any]:
    """Report which stage artifacts are present and hash them."""
    records: list[dict[str, Any]] = []
    for stage in STAGES:
        artifacts = []
        for relative in STAGE_ARTIFACTS.get(stage, ()):
            target = RUN_ROOT / relative
            artifacts.append(
                {
                    "path": relative,
                    "present": target.is_file(),
                    "bytes": target.stat().st_size if target.is_file() else 0,
                    "sha256": sha256_of(target) if target.is_file() else None,
                }
            )
        complete = bool(artifacts) and all(item["present"] for item in artifacts)
        records.append(
            {
                "stage": stage,
                "status": "passed" if complete else ("pending" if artifacts else "no_artifact"),
                "artifacts": artifacts,
            }
        )
    passed = sum(1 for r in records if r["status"] == "passed")
    return {
        "run_id": RUN_ROOT.name,
        "stage_count": len(STAGES),
        "passed": passed,
        "pending": sum(1 for r in records if r["status"] == "pending"),
        "stages": records,
        "offline": True,
        "provider": "qoder_session",
        "model_name": "qwen3.8-max",
        "dashscope_api_used": False,
    }


def main() -> int:
    """Print the replay summary and optionally write it to a file."""
    parser = argparse.ArgumentParser(description="Replay harness stages offline.")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    summary = replay()
    sys.stdout.write(
        f"[harness-copy] stages={summary['stage_count']} "
        f"passed={summary['passed']} pending={summary['pending']}\\n"
    )
    for record in summary["stages"]:
        sys.stdout.write(f"  {record['stage']:<22} {record['status']}\\n")
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

# ---------------------------------------------------------------- launch script
add(
    "../../publish/launch-local.ps1",
    """<#
.SYNOPSIS
    Launch the round-2 local web product with no external network dependency.

.DESCRIPTION
    Serves publish/local-product over 127.0.0.1 and opens the default browser.
    Requires Python 3.10 or newer on PATH. No API key is read or used.

.EXAMPLE
    pwsh -File launch-local.ps1
    pwsh -File launch-local.ps1 -Port 9000 -NoBrowser
#>

[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$RunRoot = Split-Path -Parent $PSScriptRoot
$ProductRoot = Join-Path $PSScriptRoot 'local-product'
$SourceRoot = Join-Path $RunRoot 'workspace/source'
$IndexFile = Join-Path $ProductRoot 'index.html'

if (-not (Test-Path -LiteralPath $IndexFile)) {
    Write-Host "[launch] missing $IndexFile" -ForegroundColor Red
    Write-Host '[launch] run: python reproduce.py --stage web' -ForegroundColor Yellow
    exit 1
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    Write-Host '[launch] python not found on PATH' -ForegroundColor Red
    exit 1
}

foreach ($Key in @('DASHSCOPE_API_KEY', 'OPENAI_API_KEY', 'BAILIAN_API_KEY')) {
    if (Test-Path "Env:$Key") { Remove-Item "Env:$Key" -Force }
}

$Url = "http://127.0.0.1:$Port/index.html"
Write-Host "[launch] product root : $ProductRoot"
Write-Host "[launch] source root  : $SourceRoot"
Write-Host "[launch] url          : $Url"
Write-Host '[launch] offline      : true (no CDN, no tile server, no LLM API)'

if (-not $NoBrowser) {
    Start-Process $Url
}

Push-Location $ProductRoot
try {
    & $Python.Source -m http.server $Port --bind 127.0.0.1
}
finally {
    Pop-Location
}
""",
)


def build_harness_manifest() -> dict[str, object]:
    """Hash every file already present in the harness copy directory."""
    copy_root = SOURCE / "Qwen-Harness"
    entries: list[dict[str, object]] = []
    for path in sorted(copy_root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(copy_root).as_posix()
        if relative == "run_copy_manifest.json":
            continue
        entries.append(
            {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {
        "schema_version": 1,
        "source_run_id": RUN_ID,
        "copy_root": "workspace/source/Qwen-Harness",
        "purpose": "offline_run_copy_and_reproduction_entry",
        "offline": True,
        "provider": "qoder_session",
        "model_name": "qwen3.8-max",
        "billing_channel": "qoder_credits",
        "dashscope_api_used": False,
        "model_client_initialised": False,
        "network_calls": False,
        "stage_count": 19,
        "copied_files": entries,
        "file_count": len(entries),
    }


def main() -> int:
    """Write every scaffold file and the harness copy manifest."""
    written = 0
    for relative, content in FILES.items():
        target = SOURCE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        written += 1
    manifest_path = SOURCE / "Qwen-Harness" / "run_copy_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_harness_manifest()
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"SCAFFOLD_FILES={written}")
    print(f"HARNESS_COPY_FILES={manifest['file_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
