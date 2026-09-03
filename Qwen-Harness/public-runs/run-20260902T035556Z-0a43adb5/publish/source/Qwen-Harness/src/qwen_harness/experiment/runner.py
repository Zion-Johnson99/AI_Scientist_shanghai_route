"""Experiment runner: loads frozen snapshots and weights, executes perturbation
combinations (9 profiles × 5 dimensions × 2 directions), invokes score-candidates,
and collects ranked results.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DIMENSIONS = [
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "interest_service",
]

PERTURBATION_DIRECTIONS = ["increase", "decrease"]
PERTURBATION_MAGNITUDE = 0.30


@dataclass
class PerturbationSpec:
    """Specification for a single weight perturbation."""

    dimension: str
    direction: str  # 'increase' or 'decrease'
    magnitude: float = PERTURBATION_MAGNITUDE

    @property
    def factor(self) -> float:
        if self.direction == "increase":
            return 1.0 + self.magnitude
        return 1.0 - self.magnitude

    @property
    def variant_id(self) -> str:
        sign = "+" if self.direction == "increase" else "-"
        return f"{self.dimension}_{sign}{int(self.magnitude * 100)}pct"


@dataclass
class ProfileSpec:
    """A test profile for experimentation."""

    case_id: str
    route_mode: str
    goal: str
    target_distance_m: int
    sensitivities: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "route_mode": self.route_mode,
            "goal": self.goal,
            "target_distance_m": self.target_distance_m,
            "sensitivities": self.sensitivities,
            "interests": self.interests,
        }


@dataclass
class CombinationResult:
    """Result for a single profile × perturbation combination."""

    profile_case_id: str
    variant_id: str
    dimension: str
    direction: str
    magnitude: float
    candidate_count: int
    ranked_route_ids: list[str]
    dimension_scores: dict[str, list[float]]
    constraint_pass_rate: float
    weights_sha256: str
    error: str | None = None
    stopped: bool = False
    stop_reason: str | None = None


@dataclass
class ExperimentRunResult:
    """Aggregated result for the full experiment run."""

    combinations: list[CombinationResult] = field(default_factory=list)
    baseline_results: dict[str, CombinationResult] = field(default_factory=dict)
    frozen_snapshot_hashes: dict[str, str] = field(default_factory=dict)
    frozen_weights_sha256: str = ""
    stopped: bool = False
    stop_reason: str | None = None
    errors: list[str] = field(default_factory=list)


class SnapshotIntegrityError(Exception):
    """Raised when frozen snapshot hash does not match expected value."""


class ExperimentRunner:
    """Orchestrates the full perturbation experiment.

    Responsibilities:
    - Load and freeze snapshots (route catalog, environment dashboard, weights).
    - Verify snapshot integrity before and during execution.
    - Execute all profile × dimension × direction combinations.
    - Invoke the evaluation adapter for scoring.
    - Collect and structure results.
    """

    def __init__(
        self,
        route_catalog_path: Path,
        environment_dashboard_path: Path,
        weights_path: Path,
        profiles: list[ProfileSpec],
        score_candidates_fn: Any,
        quality_gates: dict[str, Any] | None = None,
    ) -> None:
        self._route_catalog_path = route_catalog_path
        self._environment_dashboard_path = environment_dashboard_path
        self._weights_path = weights_path
        self._profiles = profiles
        self._score_candidates_fn = score_candidates_fn
        self._quality_gates = quality_gates or {}

        self._frozen_route_hash: str = ""
        self._frozen_env_hash: str = ""
        self._frozen_weights_sha256: str = ""
        self._baseline_weights: dict[str, float] = {}
        self._route_catalog: list[dict[str, Any]] = []
        self._environment_dashboard: dict[str, Any] = {}

    def freeze_snapshots(self) -> dict[str, str]:
        """Load and freeze all data snapshots, computing SHA256 hashes.

        Returns:
            Dict mapping snapshot name to its SHA256 hash.

        Raises:
            FileNotFoundError: If any required file is missing.
            json.JSONDecodeError: If any file is not valid JSON.
        """
        self._route_catalog = self._load_json(self._route_catalog_path)
        self._environment_dashboard = self._load_json(self._environment_dashboard_path)
        self._baseline_weights = self._load_json(self._weights_path)

        self._frozen_route_hash = self._compute_file_hash(self._route_catalog_path)
        self._frozen_env_hash = self._compute_file_hash(self._environment_dashboard_path)
        self._frozen_weights_sha256 = self._compute_weights_hash(self._baseline_weights)

        return {
            "route_catalog": self._frozen_route_hash,
            "environment_dashboard": self._frozen_env_hash,
            "weights": self._frozen_weights_sha256,
        }

    def verify_integrity(self) -> None:
        """Verify that frozen snapshots have not been modified.

        Raises:
            SnapshotIntegrityError: If any snapshot hash has changed.
        """
        current_route_hash = self._compute_file_hash(self._route_catalog_path)
        if current_route_hash != self._frozen_route_hash:
            raise SnapshotIntegrityError(
                f"Route catalog hash mismatch: frozen={self._frozen_route_hash}, "
                f"current={current_route_hash}. Data was modified during run."
            )

        current_env_hash = self._compute_file_hash(self._environment_dashboard_path)
        if current_env_hash != self._frozen_env_hash:
            raise SnapshotIntegrityError(
                f"Environment dashboard hash mismatch: frozen={self._frozen_env_hash}, "
                f"current={current_env_hash}. Data was modified during run."
            )

    def run_baseline(self, profile: ProfileSpec) -> CombinationResult:
        """Run baseline (unperturbed weights) for a single profile.

        Args:
            profile: The profile to evaluate.

        Returns:
            CombinationResult with baseline ranking.
        """
        return self._execute_single(
            profile=profile,
            weights=self._baseline_weights,
            variant_id="B2_multi_environment",
            dimension="none",
            direction="none",
            magnitude=0.0,
        )

    def run_perturbation(
        self, profile: ProfileSpec, spec: PerturbationSpec
    ) -> CombinationResult:
        """Run a single perturbation for a profile.

        Args:
            profile: The profile to evaluate.
            spec: The perturbation specification.

        Returns:
            CombinationResult with perturbed ranking.
        """
        perturbed_weights = self._perturb_weights(self._baseline_weights, spec)
        return self._execute_single(
            profile=profile,
            weights=perturbed_weights,
            variant_id=spec.variant_id,
            dimension=spec.dimension,
            direction=spec.direction,
            magnitude=spec.magnitude,
        )

    def run_all(self) -> ExperimentRunResult:
        """Execute the full experiment: all profiles × dimensions × directions.

        Returns:
            ExperimentRunResult with all combination results.
        """
        result = ExperimentRunResult(
            frozen_snapshot_hashes={
                "route_catalog": self._frozen_route_hash,
                "environment_dashboard": self._frozen_env_hash,
                "weights": self._frozen_weights_sha256,
            },
            frozen_weights_sha256=self._frozen_weights_sha256,
        )

        max_failed_dimensions = self._quality_gates.get("max_failed_dimensions", 2)
        jaccard_threshold = self._quality_gates.get("jaccard_threshold", 0.6)
        min_candidates = self._quality_gates.get("min_candidates", 5)

        failed_dimensions: set[str] = set()

        for profile in self._profiles:
            # Run baseline for this profile
            baseline_result = self.run_baseline(profile)
            result.baseline_results[profile.case_id] = baseline_result

            if baseline_result.error:
                result.errors.append(
                    f"Baseline failed for {profile.case_id}: {baseline_result.error}"
                )
                continue

            if baseline_result.candidate_count < min_candidates:
                logger.warning(
                    "Profile %s has %d candidates (< %d), marking as insufficient sample",
                    profile.case_id,
                    baseline_result.candidate_count,
                    min_candidates,
                )

            # Run perturbations for each dimension and direction
            for dimension in DIMENSIONS:
                for direction in PERTURBATION_DIRECTIONS:
                    spec = PerturbationSpec(dimension=dimension, direction=direction)

                    # Verify integrity before each combination
                    try:
                        self.verify_integrity()
                    except SnapshotIntegrityError as e:
                        result.stopped = True
                        result.stop_reason = str(e)
                        logger.error("Snapshot integrity failure: %s", e)
                        return result

                    combo_result = self.run_perturbation(profile, spec)
                    result.combinations.append(combo_result)

                    if combo_result.error:
                        result.errors.append(
                            f"Perturbation failed for {profile.case_id} "
                            f"{spec.variant_id}: {combo_result.error}"
                        )
                        continue

                    # Check constraint pass rate consistency
                    if (
                        baseline_result.constraint_pass_rate > 0
                        and combo_result.constraint_pass_rate
                        != baseline_result.constraint_pass_rate
                    ):
                        result.stopped = True
                        result.stop_reason = (
                            f"Constraint pass rate changed after perturbation: "
                            f"baseline={baseline_result.constraint_pass_rate}, "
                            f"perturbed={combo_result.constraint_pass_rate} "
                            f"for {profile.case_id} {spec.variant_id}. "
                            f"Perturbation may be affecting constraint logic."
                        )
                        logger.error(result.stop_reason)
                        return result

            # Check stop condition: too many failed dimensions
            if len(failed_dimensions) > max_failed_dimensions:
                result.stopped = True
                result.stop_reason = (
                    f"More than {max_failed_dimensions} dimensions failed "
                    f"(failed: {sorted(failed_dimensions)}). Hypothesis falsified."
                )
                logger.error(result.stop_reason)
                return result

        return result

    def generate_perturbation_plan(self) -> list[dict[str, Any]]:
        """Generate the full perturbation plan without executing.

        Returns:
            List of planned combinations with metadata.
        """
        plan: list[dict[str, Any]] = []
        for profile in self._profiles:
            for dimension in DIMENSIONS:
                for direction in PERTURBATION_DIRECTIONS:
                    spec = PerturbationSpec(dimension=dimension, direction=direction)
                    plan.append(
                        {
                            "profile_case_id": profile.case_id,
                            "variant_id": spec.variant_id,
                            "dimension": dimension,
                            "direction": direction,
                            "magnitude": spec.magnitude,
                            "factor": spec.factor,
                        }
                    )
        return plan

    def _execute_single(
        self,
        profile: ProfileSpec,
        weights: dict[str, float],
        variant_id: str,
        dimension: str,
        direction: str,
        magnitude: float,
    ) -> CombinationResult:
        """Execute a single scoring run with given weights.

        Args:
            profile: Profile to evaluate.
            weights: Weight configuration to use.
            variant_id: Identifier for this variant.
            dimension: Perturbed dimension (or 'none' for baseline).
            direction: Perturbation direction.
            magnitude: Perturbation magnitude.

        Returns:
            CombinationResult with ranking and metadata.
        """
        weights_sha256 = self._compute_weights_hash(weights)

        try:
            score_result = self._score_candidates_fn(
                profile=profile.to_dict(),
                weights=weights,
                route_catalog=self._route_catalog,
                environment_dashboard=self._environment_dashboard,
            )
        except Exception as e:
            logger.error(
                "score_candidates failed for %s %s: %s",
                profile.case_id,
                variant_id,
                e,
            )
            return CombinationResult(
                profile_case_id=profile.case_id,
                variant_id=variant_id,
                dimension=dimension,
                direction=direction,
                magnitude=magnitude,
                candidate_count=0,
                ranked_route_ids=[],
                dimension_scores={},
                constraint_pass_rate=0.0,
                weights_sha256=weights_sha256,
                error=str(e),
            )

        candidates = score_result.get("candidates", [])
        candidate_count = score_result.get("candidate_count", len(candidates))

        ranked_route_ids = [c["route_id"] for c in candidates]

        # Collect dimension scores
        dimension_scores: dict[str, list[float]] = {}
        for dim in DIMENSIONS:
            scores = []
            for c in candidates:
                dim_score = c.get("dimension_scores", {}).get(dim)
                if dim_score is not None:
                    scores.append(float(dim_score))
            dimension_scores[dim] = scores

        # Validate dimension completeness
        missing_dims = [
            dim for dim in DIMENSIONS if dim not in dimension_scores or not dimension_scores[dim]
        ]
        if missing_dims and candidates:
            error_msg = (
                f"Missing dimension scores for {missing_dims} in "
                f"{profile.case_id} {variant_id}. Data contract violation."
            )
            logger.error(error_msg)
            return CombinationResult(
                profile_case_id=profile.case_id,
                variant_id=variant_id,
                dimension=dimension,
                direction=direction,
                magnitude=magnitude,
                candidate_count=candidate_count,
                ranked_route_ids=ranked_route_ids,
                dimension_scores=dimension_scores,
                constraint_pass_rate=0.0,
                weights_sha256=weights_sha256,
                error=error_msg,
                stopped=True,
                stop_reason=error_msg,
            )

        # Compute constraint pass rate
        total_routes = len(self._route_catalog)
        constraint_pass_rate = candidate_count / total_routes if total_routes > 0 else 0.0

        return CombinationResult(
            profile_case_id=profile.case_id,
            variant_id=variant_id,
            dimension=dimension,
            direction=direction,
            magnitude=magnitude,
            candidate_count=candidate_count,
            ranked_route_ids=ranked_route_ids,
            dimension_scores=dimension_scores,
            constraint_pass_rate=constraint_pass_rate,
            weights_sha256=weights_sha256,
        )

    def _perturb_weights(
        self, base_weights: dict[str, float], spec: PerturbationSpec
    ) -> dict[str, float]:
        """Create perturbed weights by scaling a single dimension.

        The perturbation scales the target dimension's weight by the factor,
        then re-normalizes all weights to sum to 1.0.

        Args:
            base_weights: Original weight dictionary.
            spec: Perturbation specification.

        Returns:
            New weight dictionary with perturbation applied.
        """
        perturbed = copy.deepcopy(base_weights)

        if spec.dimension not in perturbed:
            raise ValueError(
                f"Dimension '{spec.dimension}' not found in weights. "
                f"Available: {list(perturbed.keys())}"
            )

        perturbed[spec.dimension] = perturbed[spec.dimension] * spec.factor

        # Re-normalize to sum to 1.0
        total = sum(perturbed.values())
        if total > 0:
            perturbed = {k: v / total for k, v in perturbed.items()}

        return perturbed

    @staticmethod
    def _load_json(path: Path) -> Any:
        """Load and parse a JSON file.

        Args:
            path: Path to the JSON file.

        Returns:
            Parsed JSON content.

        Raises:
            FileNotFoundError: If file does not exist.
            json.JSONDecodeError: If file is not valid JSON.
        """
        if not path.exists():
            raise FileNotFoundError(f"Required file not found: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _compute_file_hash(path: Path) -> str:
        """Compute SHA256 hash of a file.

        Args:
            path: Path to the file.

        Returns:
            Hex-encoded SHA256 hash string.
        """
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _compute_weights_hash(weights: dict[str, float]) -> str:
        """Compute SHA256 hash of a weights dictionary.

        Uses canonical JSON serialization (sorted keys, no extra whitespace)
        for deterministic hashing.

        Args:
            weights: Weight dictionary.

        Returns:
            Hex-encoded SHA256 hash string.
        """
        canonical = json.dumps(weights, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_default_profiles() -> list[ProfileSpec]:
    """Build the 9 default experiment profiles.

    Returns:
        List of ProfileSpec instances matching the experiment design.
    """
    return [
        ProfileSpec(
            case_id="P01_walk_balanced",
            route_mode="walk",
            goal="balanced",
            target_distance_m=3000,
        ),
        ProfileSpec(
            case_id="P02_run_balanced",
            route_mode="run",
            goal="balanced",
            target_distance_m=5000,
        ),
        ProfileSpec(
            case_id="P03_bike_balanced",
            route_mode="bike",
            goal="balanced",
            target_distance_m=8000,
        ),
        ProfileSpec(
            case_id="P04_walk_health_environment",
            route_mode="walk",
            goal="health_environment",
            target_distance_m=3000,
            sensitivities=["pm25", "pollen", "noise"],
            interests=["waterside", "park"],
        ),
        ProfileSpec(
            case_id="P05_run_health_environment",
            route_mode="run",
            goal="health_environment",
            target_distance_m=5000,
            sensitivities=["pm25", "noise"],
            interests=["quiet", "park"],
        ),
        ProfileSpec(
            case_id="P06_bike_nearby",
            route_mode="bike",
            goal="nearby",
            target_distance_m=8000,
            interests=["convenience", "toilet"],
        ),
        ProfileSpec(
            case_id="P07_walk_scenery",
            route_mode="walk",
            goal="scenery",
            target_distance_m=3000,
            sensitivities=["pollen"],
            interests=["waterside", "park", "quiet"],
        ),
        ProfileSpec(
            case_id="P08_run_scenery",
            route_mode="run",
            goal="scenery",
            target_distance_m=5000,
            sensitivities=["pm25"],
            interests=["waterside", "quiet"],
        ),
        ProfileSpec(
            case_id="P09_bike_health_environment",
            route_mode="bike",
            goal="health_environment",
            target_distance_m=8000,
            sensitivities=["pm25", "pollen", "noise"],
            interests=["park", "convenience"],
        ),
    ]


def create_runner_from_config(
    config: dict[str, Any],
    score_candidates_fn: Any,
) -> ExperimentRunner:
    """Create an ExperimentRunner from a configuration dictionary.

    Args:
        config: Configuration containing paths and quality gates.
            Expected keys:
            - route_catalog_path: str or Path
            - environment_dashboard_path: str or Path
            - weights_path: str or Path
            - quality_gates: dict (optional)
        score_candidates_fn: Callable that invokes score-candidates.

    Returns:
        Configured ExperimentRunner instance.
    """
    return ExperimentRunner(
        route_catalog_path=Path(config["route_catalog_path"]),
        environment_dashboard_path=Path(config["environment_dashboard_path"]),
        weights_path=Path(config["weights_path"]),
        profiles=build_default_profiles(),
        score_candidates_fn=score_candidates_fn,
        quality_gates=config.get("quality_gates", {}),
    )
