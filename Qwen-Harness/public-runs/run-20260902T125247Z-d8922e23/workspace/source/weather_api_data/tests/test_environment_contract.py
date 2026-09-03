"""Contract tests for the 54-cell environment dashboard."""

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
