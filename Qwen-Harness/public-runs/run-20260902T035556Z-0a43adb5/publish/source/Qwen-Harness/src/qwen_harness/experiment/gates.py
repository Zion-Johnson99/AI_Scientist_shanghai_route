"""Gate evaluation for experiment results.

Applies quality_gates.json thresholds to determine hypothesis support status
and trigger stop conditions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SupportStatus(str, Enum):
    """Hypothesis support status."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class StopReason(str, Enum):
    """Reasons for stopping the experiment."""

    INSUFFICIENT_CANDIDATES = "insufficient_candidates"
    ENVIRONMENT_DATA_UNAVAILABLE = "environment_data_unavailable"
    CONSTRAINT_PASS_RATE_CHANGED = "constraint_pass_rate_changed"
    MISSING_DIMENSION_SCORES = "missing_dimension_scores"
    TOO_MANY_FAILED_DIMENSIONS = "too_many_failed_dimensions"
    DATA_HASH_MISMATCH = "data_hash_mismatch"
    PROFILE_MISUSE = "profile_misuse"


@dataclass
class GateThresholds:
    """Thresholds loaded from quality_gates.json."""

    jaccard_threshold: float = 0.6
    spearman_threshold: float = 0.85
    max_failed_dimensions: int = 2
    min_candidates: int = 5
    constraint_pass_rate_tolerance: float = 0.0

    @classmethod
    def from_file(cls, path: Path) -> "GateThresholds":
        """Load thresholds from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            jaccard_threshold=data.get("jaccard_threshold", 0.6),
            spearman_threshold=data.get("spearman_threshold", 0.85),
            max_failed_dimensions=data.get("max_failed_dimensions", 2),
            min_candidates=data.get("min_candidates", 5),
            constraint_pass_rate_tolerance=data.get(
                "constraint_pass_rate_tolerance", 0.0
            ),
        )


@dataclass
class CombinationResult:
    """Result for a single profile x dimension x direction combination."""

    profile_id: str
    dimension: str
    direction: str
    jaccard_top5: float | None = None
    spearman_rank: float | None = None
    candidate_count: int = 0
    constraint_pass_rate: float | None = None
    excluded: bool = False
    exclusion_reason: str | None = None


@dataclass
class DimensionSummary:
    """Summary for a single dimension across all profiles and directions."""

    dimension: str
    failed_combinations: int = 0
    total_combinations: int = 0
    excluded_combinations: int = 0
    passed: bool = True


@dataclass
class GateResult:
    """Overall gate evaluation result."""

    status: SupportStatus
    stop_triggered: bool = False
    stop_reason: StopReason | None = None
    stop_message: str | None = None
    dimension_summaries: list[DimensionSummary] = field(default_factory=list)
    failed_dimensions: list[str] = field(default_factory=list)
    excluded_combinations: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_gates(
    combinations: list[CombinationResult],
    thresholds: GateThresholds,
    baseline_constraint_pass_rate: float | None = None,
) -> GateResult:
    """Evaluate all combination results against gate thresholds.

    Args:
        combinations: Results for each profile x dimension x direction.
        thresholds: Gate thresholds from quality_gates.json.
        baseline_constraint_pass_rate: Expected constraint pass rate under
            baseline weights. If provided, any deviation triggers a stop.

    Returns:
        GateResult with support status, stop conditions, and summaries.
    """
    # Check constraint pass rate consistency first
    if baseline_constraint_pass_rate is not None:
        for combo in combinations:
            if combo.constraint_pass_rate is not None:
                diff = abs(
                    combo.constraint_pass_rate - baseline_constraint_pass_rate
                )
                if diff > thresholds.constraint_pass_rate_tolerance:
                    return GateResult(
                        status=SupportStatus.INCONCLUSIVE,
                        stop_triggered=True,
                        stop_reason=StopReason.CONSTRAINT_PASS_RATE_CHANGED,
                        stop_message=(
                            f"Constraint pass rate changed from "
                            f"{baseline_constraint_pass_rate:.4f} to "
                            f"{combo.constraint_pass_rate:.4f} for "
                            f"{combo.profile_id}/{combo.dimension}/"
                            f"{combo.direction}. This indicates perturbation "
                            f"affected constraint logic, not just ranking."
                        ),
                    )

    # Mark combinations with insufficient candidates as excluded
    excluded_combinations: list[dict[str, str]] = []
    for combo in combinations:
        if combo.candidate_count < thresholds.min_candidates:
            combo.excluded = True
            combo.exclusion_reason = (
                f"Insufficient candidates: {combo.candidate_count} < "
                f"{thresholds.min_candidates}"
            )
            excluded_combinations.append(
                {
                    "profile_id": combo.profile_id,
                    "dimension": combo.dimension,
                    "direction": combo.direction,
                    "reason": combo.exclusion_reason,
                }
            )

    # Group by dimension and compute pass/fail
    dimensions: dict[str, list[CombinationResult]] = {}
    for combo in combinations:
        if combo.dimension not in dimensions:
            dimensions[combo.dimension] = []
        dimensions[combo.dimension].append(combo)

    dimension_summaries: list[DimensionSummary] = []
    failed_dimensions: list[str] = []

    for dim, combos in sorted(dimensions.items()):
        active = [c for c in combos if not c.excluded]
        excluded_count = len(combos) - len(active)

        failed_count = 0
        for combo in active:
            if combo.jaccard_top5 is not None:
                if combo.jaccard_top5 < thresholds.jaccard_threshold:
                    failed_count += 1
            elif combo.spearman_rank is not None:
                if combo.spearman_rank < thresholds.spearman_threshold:
                    failed_count += 1

        passed = failed_count == 0
        summary = DimensionSummary(
            dimension=dim,
            failed_combinations=failed_count,
            total_combinations=len(combos),
            excluded_combinations=excluded_count,
            passed=passed,
        )
        dimension_summaries.append(summary)

        if not passed:
            failed_dimensions.append(dim)

    # Determine overall status
    total_active = sum(
        1 for c in combinations if not c.excluded
    )

    if total_active == 0:
        return GateResult(
            status=SupportStatus.INCONCLUSIVE,
            stop_triggered=False,
            dimension_summaries=dimension_summaries,
            failed_dimensions=failed_dimensions,
            excluded_combinations=excluded_combinations,
            details={"reason": "All combinations excluded due to insufficient candidates."},
        )

    if len(failed_dimensions) > thresholds.max_failed_dimensions:
        return GateResult(
            status=SupportStatus.UNSUPPORTED,
            stop_triggered=True,
            stop_reason=StopReason.TOO_MANY_FAILED_DIMENSIONS,
            stop_message=(
                f"{len(failed_dimensions)} dimensions failed "
                f"(threshold: max {thresholds.max_failed_dimensions}). "
                f"Failed: {', '.join(failed_dimensions)}. "
                f"Hypothesis is falsified."
            ),
            dimension_summaries=dimension_summaries,
            failed_dimensions=failed_dimensions,
            excluded_combinations=excluded_combinations,
        )

    if len(failed_dimensions) == 0 and len(excluded_combinations) == 0:
        return GateResult(
            status=SupportStatus.SUPPORTED,
            stop_triggered=False,
            dimension_summaries=dimension_summaries,
            failed_dimensions=[],
            excluded_combinations=[],
        )

    if len(failed_dimensions) == 0 and len(excluded_combinations) > 0:
        return GateResult(
            status=SupportStatus.PARTIALLY_SUPPORTED,
            stop_triggered=False,
            dimension_summaries=dimension_summaries,
            failed_dimensions=[],
            excluded_combinations=excluded_combinations,
            details={
                "reason": (
                    "No dimension failed, but some combinations were excluded "
                    "due to insufficient candidates."
                )
            },
        )

    # Some dimensions failed but within threshold
    return GateResult(
        status=SupportStatus.PARTIALLY_SUPPORTED,
        stop_triggered=False,
        dimension_summaries=dimension_summaries,
        failed_dimensions=failed_dimensions,
        excluded_combinations=excluded_combinations,
        details={
            "reason": (
                f"{len(failed_dimensions)} dimension(s) failed but within "
                f"max_failed_dimensions={thresholds.max_failed_dimensions}."
            )
        },
    )


def check_stop_conditions(
    combinations: list[CombinationResult],
    thresholds: GateThresholds,
    environment_status: str | None = None,
    data_hash_match: bool = True,
) -> tuple[bool, StopReason | None, str | None]:
    """Check pre-execution stop conditions before running experiments.

    Args:
        combinations: Pre-check results (e.g., baseline candidate counts).
        thresholds: Gate thresholds.
        environment_status: Status of environment data snapshot.
        data_hash_match: Whether frozen data hashes match current files.

    Returns:
        Tuple of (should_stop, reason, message).
    """
    if not data_hash_match:
        return (
            True,
            StopReason.DATA_HASH_MISMATCH,
            "Data file hashes do not match frozen snapshot. "
            "Data may have been modified during the run.",
        )

    if environment_status in ("error", "no_data"):
        return (
            True,
            StopReason.ENVIRONMENT_DATA_UNAVAILABLE,
            f"Environment snapshot status is '{environment_status}' "
            f"with no last-known-good fallback available.",
        )

    for combo in combinations:
        if combo.candidate_count < thresholds.min_candidates:
            return (
                True,
                StopReason.INSUFFICIENT_CANDIDATES,
                f"Profile {combo.profile_id} has only "
                f"{combo.candidate_count} feasible candidates under "
                f"baseline weights (minimum: {thresholds.min_candidates}). "
                f"Cannot form top-5 set.",
            )

    return (False, None, None)
