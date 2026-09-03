"""Tests for evaluation_model_qwen scoring and constraints."""

from evaluation_model_qwen.constraints import (
    apply_hard_constraints,
)
from evaluation_model_qwen.models import (
    EnvironmentBlock,
    EnvironmentDashboard,
    EnvironmentData,
    EnvironmentRouteRecord,
    RiskAssessment,
    RouteEntry,
    ScoredRoute,
    UserProfile,
)
from evaluation_model_qwen.scoring import evaluate_risk, score_routes

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_route(
    route_id: str = "W001",
    route_mode: str = "walk",
    distance_m: float = 3000.0,
) -> RouteEntry:
    return RouteEntry(
        route_id=route_id,
        route_name=f"Test route {route_id}",
        route_mode=route_mode,
        distance_m=distance_m,
        validation_status="accepted",
        geometry_status="valid",
    )


def _make_env_record(
    route_id: str = "W001",
    pm25: float = 35.0,
    noise: float = 50.0,
    pollen: float = 3.0,
) -> EnvironmentRouteRecord:
    return EnvironmentRouteRecord(
        route_id=route_id,
        pm2_5=EnvironmentBlock(value=pm25, unit="ug/m3", estimated=False),
        noise=EnvironmentBlock(value=noise, unit="index_0_100", estimated=True),
        pollen_daily=EnvironmentBlock(value=pollen, unit="level", estimated=True),
    )


def _make_profile(
    route_mode: str = "walk",
    target_distance_m: float = 3000.0,
    goal: str = "balanced",
    sensitivities: list[str] | None = None,
    interests: list[str] | None = None,
) -> UserProfile:
    return UserProfile(
        route_mode=route_mode,
        goal=goal,
        target_distance_m=target_distance_m,
        sensitivities=sensitivities or [],
        interests=interests or [],
    )


def _default_weights() -> dict[str, float]:
    return {
        "environment_health": 0.25,
        "sport_match": 0.20,
        "access_convenience": 0.15,
        "route_quality": 0.20,
        "interest_service": 0.20,
    }


def _safe_environment() -> EnvironmentData:
    """Return environment data that does NOT trigger safety pause."""
    return EnvironmentData(
        temperature_c=22.0,
        feels_like_c=23.0,
        precipitation_mm=0.0,
        wind_gust_ms=3.0,
        aqi=60,
    )


def _dangerous_environment() -> EnvironmentData:
    """Return environment data that triggers safety pause."""
    return EnvironmentData(
        temperature_c=38.0,
        feels_like_c=42.0,
        precipitation_mm=15.0,
        wind_gust_ms=20.0,
        aqi=250,
    )


# ---------------------------------------------------------------------------
# Hard constraint tests
# ---------------------------------------------------------------------------


class TestHardConstraints:
    """Tests for hard constraint filtering."""

    def test_distance_deviation_within_tolerance(self):
        """Route within 15% distance deviation passes."""
        routes = [_make_route(distance_m=3200.0)]  # 6.7% deviation from 3000
        profile = _make_profile(target_distance_m=3000.0)
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert len(result) == 1
        assert result[0].route_id == "W001"

    def test_distance_deviation_exceeds_tolerance(self):
        """Route exceeding 15% distance deviation is filtered out."""
        routes = [_make_route(distance_m=3500.0)]  # 16.7% deviation from 3000
        profile = _make_profile(target_distance_m=3000.0)
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert len(result) == 0

    def test_distance_deviation_exact_boundary(self):
        """Route at exactly 15% deviation passes (boundary inclusive)."""
        routes = [_make_route(distance_m=3450.0)]  # exactly 15% from 3000
        profile = _make_profile(target_distance_m=3000.0)
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert len(result) == 1

    def test_mode_mismatch_filtered(self):
        """Route with different mode is filtered out."""
        routes = [_make_route(route_mode="run")]
        profile = _make_profile(route_mode="walk")
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert len(result) == 0

    def test_mode_match_passes(self):
        """Route with matching mode passes."""
        routes = [_make_route(route_mode="walk")]
        profile = _make_profile(route_mode="walk")
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert len(result) == 1

    def test_multiple_routes_mixed(self):
        """Only routes passing all constraints remain."""
        routes = [
            _make_route(route_id="W001", route_mode="walk", distance_m=3000.0),
            _make_route(route_id="W002", route_mode="walk", distance_m=4000.0),  # 33% dev
            _make_route(route_id="R001", route_mode="run", distance_m=3000.0),  # wrong mode
            _make_route(route_id="W003", route_mode="walk", distance_m=2800.0),  # 6.7% dev
        ]
        profile = _make_profile(route_mode="walk", target_distance_m=3000.0)
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        ids = [r.route_id for r in result]
        assert "W001" in ids
        assert "W003" in ids
        assert "W002" not in ids
        assert "R001" not in ids


# ---------------------------------------------------------------------------
# Safety threshold tests
# ---------------------------------------------------------------------------


class TestSafetyThresholds:
    """Tests for safety pause logic."""

    def test_safe_environment_no_pause(self):
        """Safe conditions do not trigger pause."""
        env = _safe_environment()
        risk = evaluate_risk(env)
        assert isinstance(risk, RiskAssessment)
        assert risk.paused is False

    def test_dashboard_null_current_values_use_safe_defaults(self):
        """Missing live weather values must not crash route recommendations."""
        dashboard = EnvironmentDashboard(
            current={
                "temperature_c": None,
                "precipitation_mm": None,
                "wind_speed_ms": None,
                "aqi_value": None,
            }
        )

        risk = evaluate_risk(dashboard)

        assert risk.paused is False

    def test_dangerous_environment_triggers_pause(self):
        """Dangerous conditions trigger pause."""
        env = _dangerous_environment()
        risk = evaluate_risk(env)
        assert risk.paused is True
        assert len(risk.reasons) > 0

    def test_high_aqi_triggers_pause(self):
        """AQI above threshold triggers pause."""
        env = EnvironmentData(
            temperature_c=22.0,
            feels_like_c=23.0,
            precipitation_mm=0.0,
            wind_gust_ms=3.0,
            aqi=210,
        )
        risk = evaluate_risk(env)
        assert risk.paused is True
        assert any("aqi" in r.lower() or "AQI" in r for r in risk.reasons)

    def test_heavy_precipitation_triggers_pause(self):
        """Heavy precipitation triggers pause."""
        env = EnvironmentData(
            temperature_c=22.0,
            feels_like_c=23.0,
            precipitation_mm=12.0,
            wind_gust_ms=3.0,
            aqi=60,
        )
        risk = evaluate_risk(env)
        assert risk.paused is True

    def test_high_wind_gust_triggers_pause(self):
        """High wind gust triggers pause."""
        env = EnvironmentData(
            temperature_c=22.0,
            feels_like_c=23.0,
            precipitation_mm=0.0,
            wind_gust_ms=18.0,
            aqi=60,
        )
        risk = evaluate_risk(env)
        assert risk.paused is True

    def test_extreme_feels_like_temperature_triggers_pause(self):
        """Extreme feels-like temperature triggers pause."""
        env = EnvironmentData(
            temperature_c=36.0,
            feels_like_c=41.0,
            precipitation_mm=0.0,
            wind_gust_ms=3.0,
            aqi=60,
        )
        risk = evaluate_risk(env)
        assert risk.paused is True


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


class TestScoreRoutes:
    """Tests for five-dimension scoring."""

    def test_score_routes_returns_all_dimensions(self):
        """Each scored route contains all five dimension scores."""
        routes = [_make_route(route_id="W001", distance_m=3000.0)]
        env_records = [_make_env_record(route_id="W001")]
        profile = _make_profile()
        weights = _default_weights()

        results = score_routes(routes, env_records, profile, weights)
        assert len(results) == 1
        scored = results[0]
        assert isinstance(scored, ScoredRoute)
        assert scored.route_id == "W001"
        assert scored.route_name == "Test route W001"
        assert scored.route_mode == "walk"
        assert scored.distance_m == 3000.0
        assert hasattr(scored, "environment_health")
        assert hasattr(scored, "sport_match")
        assert hasattr(scored, "access_convenience")
        assert hasattr(scored, "route_quality")
        assert hasattr(scored, "interest_service")
        # All scores should be numeric
        assert isinstance(scored.environment_health, (int, float))
        assert isinstance(scored.sport_match, (int, float))
        assert isinstance(scored.access_convenience, (int, float))
        assert isinstance(scored.route_quality, (int, float))
        assert isinstance(scored.interest_service, (int, float))

    def test_score_routes_multiple_routes(self):
        """Multiple routes are all scored."""
        routes = [
            _make_route(route_id="W001", distance_m=3000.0),
            _make_route(route_id="W002", distance_m=3100.0),
            _make_route(route_id="W003", distance_m=2900.0),
        ]
        env_records = [
            _make_env_record(route_id="W001"),
            _make_env_record(route_id="W002", pm25=50.0),
            _make_env_record(route_id="W003", pm25=20.0),
        ]
        profile = _make_profile()
        weights = _default_weights()

        results = score_routes(routes, env_records, profile, weights)
        assert len(results) == 3
        ids = {r.route_id for r in results}
        assert ids == {"W001", "W002", "W003"}

    def test_weight_perturbation_changes_scores(self):
        """Changing weights changes the relative ordering or scores."""
        routes = [
            _make_route(route_id="W001", distance_m=3000.0),
            _make_route(route_id="W002", distance_m=3000.0),
        ]
        env_records = [
            _make_env_record(route_id="W001", pm25=20.0, noise=30.0),
            _make_env_record(route_id="W002", pm25=60.0, noise=70.0),
        ]
        profile = _make_profile(sensitivities=["pm25", "noise"])

        weights_env_heavy = {
            "environment_health": 0.60,
            "sport_match": 0.10,
            "access_convenience": 0.10,
            "route_quality": 0.10,
            "interest_service": 0.10,
        }
        weights_balanced = _default_weights()

        results_env = score_routes(routes, env_records, profile, weights_env_heavy)
        results_bal = score_routes(routes, env_records, profile, weights_balanced)

        # With environment-heavy weights, the cleaner route (W001) should
        # have a higher base_score than with balanced weights relative to W002
        env_scores = {r.route_id: r.base_score for r in results_env}
        bal_scores = {r.route_id: r.base_score for r in results_bal}

        # The gap between W001 and W002 should be larger with env-heavy weights
        gap_env = env_scores["W001"] - env_scores["W002"]
        gap_bal = bal_scores["W001"] - bal_scores["W002"]
        assert gap_env > gap_bal

    def test_weight_perturbation_30_percent(self):
        """±30% perturbation on one dimension changes scores measurably."""
        routes = [_make_route(route_id="W001", distance_m=3000.0)]
        env_records = [_make_env_record(route_id="W001")]
        profile = _make_profile()
        base_weights = _default_weights()

        # Perturb environment_health +30%
        perturbed_up = dict(base_weights)
        perturbed_up["environment_health"] = base_weights["environment_health"] * 1.3

        # Perturb environment_health -30%
        perturbed_down = dict(base_weights)
        perturbed_down["environment_health"] = base_weights["environment_health"] * 0.7

        results_base = score_routes(routes, env_records, profile, base_weights)
        results_up = score_routes(routes, env_records, profile, perturbed_up)
        results_down = score_routes(routes, env_records, profile, perturbed_down)

        # Scores should differ when weights change
        base_score = results_base[0].base_score
        up_score = results_up[0].base_score
        down_score = results_down[0].base_score

        # At least one should differ from base
        assert not (base_score == up_score == down_score), (
            "Weight perturbation should change base_score"
        )

    def test_empty_routes_returns_empty(self):
        """No routes yields empty result list."""
        profile = _make_profile()
        weights = _default_weights()
        results = score_routes([], [], profile, weights)
        assert results == []

    def test_no_matching_env_records(self):
        """Routes without environment records still get scored (with defaults)."""
        routes = [_make_route(route_id="W001", distance_m=3000.0)]
        env_records = []  # No environment data
        profile = _make_profile()
        weights = _default_weights()

        results = score_routes(routes, env_records, profile, weights)
        # Should still return a result (with estimated/default env scores)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# No-candidate scenario tests
# ---------------------------------------------------------------------------


class TestNoCandidateScenarios:
    """Tests for scenarios where no candidates pass constraints."""

    def test_all_routes_filtered_by_distance(self):
        """All routes exceed distance tolerance → empty candidates."""
        routes = [
            _make_route(route_id="W001", distance_m=5000.0),  # 67% dev
            _make_route(route_id="W002", distance_m=6000.0),  # 100% dev
        ]
        profile = _make_profile(target_distance_m=3000.0)
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert result == []

    def test_all_routes_filtered_by_mode(self):
        """All routes have wrong mode → empty candidates."""
        routes = [
            _make_route(route_id="R001", route_mode="run", distance_m=3000.0),
            _make_route(route_id="B001", route_mode="bike", distance_m=3000.0),
        ]
        profile = _make_profile(route_mode="walk", target_distance_m=3000.0)
        result = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert result == []

    def test_empty_input_routes(self):
        """Empty route list yields empty candidates."""
        profile = _make_profile()
        result = apply_hard_constraints([], profile, detour_limit=0.2)
        assert result == []

    def test_safety_pause_yields_no_recommendation(self):
        """When safety pause is triggered, scoring should reflect pause."""
        env = _dangerous_environment()
        risk = evaluate_risk(env)
        assert risk.paused is True
        # In the full pipeline, paused means no recommendation is issued.
        # Here we verify the risk assessment correctly signals pause.
        assert len(risk.reasons) > 0


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestScoringIntegration:
    """Integration tests combining constraints and scoring."""

    def test_full_pipeline_walk_profile(self):
        """Full pipeline: constraints → scoring for a walk profile."""
        routes = [
            _make_route(route_id="W001", route_mode="walk", distance_m=3000.0),
            _make_route(route_id="W002", route_mode="walk", distance_m=3200.0),
            _make_route(route_id="W003", route_mode="walk", distance_m=4000.0),  # filtered
            _make_route(route_id="R001", route_mode="run", distance_m=3000.0),  # filtered
        ]
        env_records = [
            _make_env_record(route_id="W001", pm25=25.0),
            _make_env_record(route_id="W002", pm25=40.0),
            _make_env_record(route_id="W003", pm25=30.0),
            _make_env_record(route_id="R001", pm25=35.0),
        ]
        profile = _make_profile(
            route_mode="walk",
            target_distance_m=3000.0,
            sensitivities=["pm25"],
        )
        weights = _default_weights()

        # Apply constraints
        feasible = apply_hard_constraints(routes, profile, detour_limit=0.2)
        assert len(feasible) == 2
        feasible_ids = {r.route_id for r in feasible}
        assert feasible_ids == {"W001", "W002"}

        # Score feasible routes
        feasible_env = [e for e in env_records if e.route_id in feasible_ids]
        scored = score_routes(feasible, feasible_env, profile, weights)
        assert len(scored) == 2

        # W001 has lower PM2.5, should score higher on environment_health
        scores_by_id = {s.route_id: s for s in scored}
        assert scores_by_id["W001"].environment_health >= scores_by_id["W002"].environment_health

    def test_full_pipeline_bike_profile(self):
        """Full pipeline for bike mode with longer distance."""
        routes = [
            _make_route(route_id="B001", route_mode="bike", distance_m=8000.0),
            _make_route(route_id="B002", route_mode="bike", distance_m=7500.0),
            _make_route(route_id="B003", route_mode="bike", distance_m=9500.0),  # 18.75% dev
        ]
        env_records = [
            _make_env_record(route_id="B001", pm25=30.0, noise=45.0),
            _make_env_record(route_id="B002", pm25=35.0, noise=55.0),
            _make_env_record(route_id="B003", pm25=28.0, noise=40.0),
        ]
        profile = _make_profile(
            route_mode="bike",
            target_distance_m=8000.0,
            goal="nearby",
            interests=["convenience", "toilet"],
        )
        weights = _default_weights()

        feasible = apply_hard_constraints(routes, profile, detour_limit=0.2)
        # B003 has 18.75% deviation which exceeds 15%
        feasible_ids = {r.route_id for r in feasible}
        assert "B001" in feasible_ids
        assert "B002" in feasible_ids
        assert "B003" not in feasible_ids

        feasible_env = [e for e in env_records if e.route_id in feasible_ids]
        scored = score_routes(feasible, feasible_env, profile, weights)
        assert len(scored) == 2

    def test_scores_are_bounded(self):
        """All dimension scores should be within reasonable bounds."""
        routes = [_make_route(route_id="W001", distance_m=3000.0)]
        env_records = [_make_env_record(route_id="W001")]
        profile = _make_profile()
        weights = _default_weights()

        results = score_routes(routes, env_records, profile, weights)
        scored = results[0]

        for dim in [
            scored.environment_health,
            scored.sport_match,
            scored.access_convenience,
            scored.route_quality,
            scored.interest_service,
        ]:
            assert 0.0 <= dim <= 100.0, f"Score {dim} out of bounds [0, 100]"

        assert 0.0 <= scored.base_score <= 100.0
