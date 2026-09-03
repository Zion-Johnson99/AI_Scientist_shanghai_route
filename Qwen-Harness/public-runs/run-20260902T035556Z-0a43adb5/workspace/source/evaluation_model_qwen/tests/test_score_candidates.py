"""Integration tests for the score-candidates CLI and service layer.

Covers:
- Normal path: valid inputs produce complete CandidateScoreResult
- No candidates: all routes filtered by constraints
- Missing files: clear error with exit code 2
- Dimension completeness: every candidate has all five dimension scores
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures: minimal valid data files
# ---------------------------------------------------------------------------

MODULE_ROOT = Path(__file__).resolve().parent.parent


def _make_route_catalog(count: int = 6) -> list[dict]:
    """Generate a minimal route catalog with *count* routes (2 per mode)."""
    modes = ["walk", "run", "bike"]
    routes = []
    for i in range(count):
        mode = modes[i % 3]
        routes.append(
            {
                "route_id": f"R{i + 1:03d}",
                "route_name": f"Test Route {i + 1}",
                "route_mode": mode,
                "validation_status": "accepted",
                "geometry_status": "valid",
                "distance_m": 3000 + i * 500,
            }
        )
    return routes


def _make_environment_dashboard(route_ids: list[str]) -> dict:
    """Generate a minimal environment dashboard covering *route_ids*."""
    items = []
    for rid in route_ids:
        items.append(
            {
                "route_id": rid,
                "pm2_5": {
                    "value": 35.0,
                    "unit": "ug/m3",
                    "estimated": True,
                    "status": "ok",
                    "confidence": 0.7,
                },
                "noise": {
                    "value": 45,
                    "unit": "risk_index_0_100",
                    "estimated": True,
                    "status": "ok",
                    "confidence": 0.6,
                },
                "pollen_daily": {
                    "value": 20,
                    "unit": "grains/m3",
                    "estimated": True,
                    "status": "ok",
                    "confidence": 0.5,
                },
            }
        )
    return {
        "metadata": {
            "generated_at": "2025-01-01T08:00:00Z",
            "sources": ["test"],
            "status": "ok",
        },
        "current": {
            "temperature_c": 22.0,
            "humidity_pct": 60.0,
            "wind_speed_ms": 3.0,
            "precipitation_mm": 0.0,
            "aqi": 55,
            "pm2_5_ug_m3": 30.0,
        },
        "forecast": [],
        "routes": {"items": items},
    }


def _make_profile(route_mode: str = "walk", target_distance_m: int = 3000) -> dict:
    return {
        "route_mode": route_mode,
        "goal": "balanced",
        "target_distance_m": target_distance_m,
        "sensitivities": [],
        "interests": [],
    }


def _make_weights() -> dict:
    return {
        "environment_health": 0.25,
        "sport_match": 0.20,
        "access_convenience": 0.15,
        "route_quality": 0.20,
        "interest_service": 0.20,
    }


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Write minimal valid data files into a temp directory."""
    routes = _make_route_catalog(6)
    route_ids = [r["route_id"] for r in routes]
    env = _make_environment_dashboard(route_ids)
    weights = _make_weights()
    profile = _make_profile()

    (tmp_path / "route_catalog.json").write_text(
        json.dumps(routes, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "environment_dashboard.json").write_text(
        json.dumps(env, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "weights.json").write_text(
        json.dumps(weights, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Helper: invoke CLI via subprocess
# ---------------------------------------------------------------------------


def _run_cli(
    args: list[str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run the evaluation-model-qwen CLI as a subprocess."""
    cmd = [sys.executable, "-m", "evaluation_model_qwen.cli"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or MODULE_ROOT,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Tests: normal path
# ---------------------------------------------------------------------------


class TestScoreCandidatesNormal:
    """Normal path: valid inputs produce complete output."""

    def test_output_is_valid_json(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert isinstance(output, dict)

    def test_output_schema_completeness(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)

        # Top-level required keys
        assert "profile" in output
        assert "risk" in output
        assert "data_generated_at" in output
        assert "candidate_count" in output
        assert "candidates" in output
        assert "weights_sha256" in output

    def test_candidates_have_all_five_dimensions(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)

        required_dimensions = {
            "environment_health",
            "sport_match",
            "access_convenience",
            "route_quality",
            "interest_service",
        }

        for candidate in output["candidates"]:
            assert "route_id" in candidate, "Candidate missing route_id"
            scores = candidate.get("scores", candidate.get("dimension_scores", {}))
            for dim in required_dimensions:
                assert dim in scores, (
                    f"Candidate {candidate.get('route_id')} missing dimension: {dim}"
                )
                assert 0 <= scores[dim] <= 100, f"Score out of range for {dim}: {scores[dim]}"

    def test_candidate_count_matches_candidates_length(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["candidate_count"] == len(output["candidates"])

    def test_weights_sha256_is_hex_string(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        sha = output["weights_sha256"]
        assert isinstance(sha, str)
        assert len(sha) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in sha)

    def test_only_matching_mode_routes_in_candidates(self, data_dir: Path) -> None:
        """Profile requests walk; only walk routes should appear."""
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)

        # Load catalog to check modes
        catalog = json.loads((data_dir / "route_catalog.json").read_text(encoding="utf-8"))
        walk_ids = {r["route_id"] for r in catalog if r["route_mode"] == "walk"}
        for candidate in output["candidates"]:
            assert candidate["route_id"] in walk_ids


# ---------------------------------------------------------------------------
# Tests: no candidates
# ---------------------------------------------------------------------------


class TestScoreCandidatesNoCandidates:
    """All routes filtered out by constraints."""

    def test_no_candidates_when_mode_mismatch(self, data_dir: Path) -> None:
        """Profile requests a mode not present in catalog."""
        profile = _make_profile(route_mode="swim", target_distance_m=3000)
        (data_dir / "profile_swim.json").write_text(json.dumps(profile), encoding="utf-8")
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile_swim.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["candidate_count"] == 0
        assert output["candidates"] == []

    def test_no_candidates_when_distance_out_of_tolerance(self, data_dir: Path) -> None:
        """Target distance far from all routes triggers empty result."""
        profile = _make_profile(route_mode="walk", target_distance_m=100)
        (data_dir / "profile_short.json").write_text(json.dumps(profile), encoding="utf-8")
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile_short.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["candidate_count"] == 0
        assert output["candidates"] == []


# ---------------------------------------------------------------------------
# Tests: missing files
# ---------------------------------------------------------------------------


class TestScoreCandidatesMissingFiles:
    """Missing input files produce exit code 2 with clear error."""

    def test_missing_profile(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "nonexistent_profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 2
        assert "profile" in result.stderr.lower() or "not found" in result.stderr.lower()

    def test_missing_route_catalog(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "nonexistent_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 2
        assert "route" in result.stderr.lower() or "not found" in result.stderr.lower()

    def test_missing_environment_dashboard(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "nonexistent_env.json"),
                "--json",
            ]
        )
        assert result.returncode == 2
        assert "environment" in result.stderr.lower() or "not found" in result.stderr.lower()

    def test_missing_weights(self, data_dir: Path) -> None:
        result = _run_cli(
            [
                "score-candidates",
                "--profile",
                str(data_dir / "profile.json"),
                "--weights",
                str(data_dir / "nonexistent_weights.json"),
                "--route-catalog",
                str(data_dir / "route_catalog.json"),
                "--environment-dashboard",
                str(data_dir / "environment_dashboard.json"),
                "--json",
            ]
        )
        assert result.returncode == 2
        assert "weights" in result.stderr.lower() or "not found" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Tests: service layer (unit-level, no subprocess)
# ---------------------------------------------------------------------------


class TestScoreCandidatesServiceLayer:
    """Direct service function tests for dimension completeness."""

    def test_default_nested_weights_load(self) -> None:
        from evaluation_model_qwen.service import load_weights

        weights = load_weights()

        assert set(weights) == {
            "environment_health",
            "sport_match",
            "access_convenience",
            "route_quality",
            "interest_service",
        }
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_service_returns_all_dimensions(self, data_dir: Path) -> None:
        """Import service and call score_candidates directly."""
        sys.path.insert(0, str(MODULE_ROOT / "src"))
        try:
            from evaluation_model_qwen.service import score_candidates

            result = score_candidates(
                profile_path=data_dir / "profile.json",
                weights_path=data_dir / "weights.json",
                route_catalog_path=data_dir / "route_catalog.json",
                environment_dashboard_path=data_dir / "environment_dashboard.json",
            )

            assert result.candidate_count == len(result.candidates)
            required_dims = {
                "environment_health",
                "sport_match",
                "access_convenience",
                "route_quality",
                "interest_service",
            }
            for candidate in result.candidates:
                scores = candidate.scores
                for dim in required_dims:
                    assert dim in scores, f"Missing dimension: {dim}"
                    assert 0 <= scores[dim] <= 100
        finally:
            sys.path.pop(0)

    def test_service_no_candidates_returns_empty(self, data_dir: Path) -> None:
        """Service returns zero candidates when mode mismatches."""
        profile = _make_profile(route_mode="swim", target_distance_m=3000)
        profile_path = data_dir / "profile_swim_svc.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")

        sys.path.insert(0, str(MODULE_ROOT / "src"))
        try:
            from evaluation_model_qwen.service import score_candidates

            result = score_candidates(
                profile_path=profile_path,
                weights_path=data_dir / "weights.json",
                route_catalog_path=data_dir / "route_catalog.json",
                environment_dashboard_path=data_dir / "environment_dashboard.json",
            )
            assert result.candidate_count == 0
            assert result.candidates == []
        finally:
            sys.path.pop(0)

    def test_service_missing_file_raises(self, data_dir: Path) -> None:
        """Service raises FileNotFoundError for missing inputs."""
        sys.path.insert(0, str(MODULE_ROOT / "src"))
        try:
            from evaluation_model_qwen.service import score_candidates

            with pytest.raises((FileNotFoundError, SystemExit)):
                score_candidates(
                    profile_path=data_dir / "nonexistent.json",
                    weights_path=data_dir / "weights.json",
                    route_catalog_path=data_dir / "route_catalog.json",
                    environment_dashboard_path=data_dir / "environment_dashboard.json",
                )
        finally:
            sys.path.pop(0)
