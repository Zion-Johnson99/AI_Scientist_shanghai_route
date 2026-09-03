"""Experiment metrics computation.

Provides Jaccard top-k similarity, Spearman rank correlation,
dimension variance, constraint pass rate, candidate count,
and statistical summaries (median, IQR, bootstrap CI with fixed seed).
"""

from __future__ import annotations

import random
import statistics
from typing import Sequence


def jaccard_top_k(
    baseline_ids: Sequence[str],
    perturbed_ids: Sequence[str],
    k: int = 5,
) -> float:
    """Compute Jaccard similarity of the top-k route ID sets.

    The effective truncation length is min(k, len(a), len(b)); both
    lists are truncated to that common length before set comparison.
    Returns 1.0 if both truncated sets are empty (vacuous truth).
    Returns 0.0 if exactly one set is empty.
    """
    if bool(baseline_ids) != bool(perturbed_ids):
        return 0.0

    effective_k = min(k, len(baseline_ids), len(perturbed_ids))
    set_a = set(baseline_ids[:effective_k])
    set_b = set(perturbed_ids[:effective_k])
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def jaccard_top5(
    baseline_ids: Sequence[str],
    perturbed_ids: Sequence[str],
    k: int = 5,
) -> float:
    """Alias for jaccard_top_k kept for backward compatibility."""
    return jaccard_top_k(baseline_ids, perturbed_ids, k=k)


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Compute 1-based average ranks for a sequence, handling ties."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for idx in range(i, j + 1):
            ranks[indexed[idx]] = avg_rank
        i = j + 1
    return ranks


def spearman_rank_correlation(
    a: Sequence[float],
    b: Sequence[float],
) -> float:
    """Compute Spearman rank correlation between two sequences of values.

    Uses average rank method for ties.
    Returns 1.0 for single-element sequences.
    Raises ValueError for empty or mismatched-length inputs.
    """
    if len(a) == 0 or len(b) == 0:
        raise ValueError("Both sequences must be non-empty")
    if len(a) != len(b):
        raise ValueError("Sequences must have the same length")
    n = len(a)
    if n == 1:
        return 1.0

    ranks_a = _average_ranks(a)
    ranks_b = _average_ranks(b)

    mean_a = sum(ranks_a) / n
    mean_b = sum(ranks_b) / n

    cov = sum((ranks_a[i] - mean_a) * (ranks_b[i] - mean_b) for i in range(n))
    var_a = sum((ranks_a[i] - mean_a) ** 2 for i in range(n))
    var_b = sum((ranks_b[i] - mean_b) ** 2 for i in range(n))

    if var_a == 0.0 or var_b == 0.0:
        return 1.0

    rho = cov / (var_a * var_b) ** 0.5
    return rho


def spearman_rank(
    baseline_order: Sequence[str],
    perturbed_order: Sequence[str],
) -> float:
    """Compute Spearman rank correlation between two orderings of route IDs.

    Both sequences must contain the same set of route IDs.
    Returns 1.0 for identical orderings, -1.0 for reversed.
    Raises ValueError if the ID sets differ.
    """
    if set(baseline_order) != set(perturbed_order):
        raise ValueError("baseline_order and perturbed_order must contain the same route IDs")
    n = len(baseline_order)
    if n == 0:
        return 1.0
    if n == 1:
        return 1.0

    rank_a = {rid: i + 1 for i, rid in enumerate(baseline_order)}
    rank_b = {rid: i + 1 for i, rid in enumerate(perturbed_order)}

    d_squared_sum = sum((rank_a[rid] - rank_b[rid]) ** 2 for rid in baseline_order)

    rho = 1.0 - (6.0 * d_squared_sum) / (n * (n * n - 1))
    return rho


def dimension_variance(
    dimension_scores: Sequence[float],
) -> float:
    """Compute population variance of a dimension's scores across candidates.

    Returns 0.0 for a single value.
    Raises ValueError for empty input.
    """
    if len(dimension_scores) == 0:
        raise ValueError("dimension_scores must be non-empty")
    if len(dimension_scores) == 1:
        return 0.0
    return statistics.pvariance(dimension_scores)


def constraint_pass_rate(
    results: Sequence[bool],
) -> float:
    """Compute the fraction of candidates passing hard constraints.

    Accepts a sequence of booleans (True = pass).
    Raises ValueError for empty input.
    """
    if len(results) == 0:
        raise ValueError("results must be non-empty")
    return sum(1 for r in results if r) / len(results)


def candidate_count(candidates: Sequence[object]) -> int:
    """Return the number of feasible candidates."""
    return len(candidates)


def median(values: Sequence[float]) -> float:
    """Compute median of a sequence.

    Raises ValueError for empty input.
    """
    if not values:
        raise ValueError("values must be non-empty")
    return statistics.median(values)


def interquartile_range(values: Sequence[float]) -> float:
    """Compute IQR (Q3 - Q1) using the median-of-halves method.

    Returns 0.0 for a single value.
    Raises ValueError for empty input.
    """
    if not values:
        raise ValueError("values must be non-empty")
    if len(values) == 1:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    lower_half = sorted_vals[:mid]
    if n % 2 == 0:
        upper_half = sorted_vals[mid:]
    else:
        upper_half = sorted_vals[mid + 1 :]
    q1 = statistics.median(lower_half)
    q3 = statistics.median(upper_half)
    return q3 - q1


def bootstrap_confidence_interval(
    values: Sequence[float],
    n_bootstrap: int = 1000,
    ci_level: float = 0.95,
    seed: int = 1234,
) -> tuple[float, float]:
    """Compute bootstrap confidence interval for the mean.

    Uses a fixed seed for reproducibility.
    Returns (lower, upper) bounds.
    Raises ValueError for empty input.
    For single value returns (value, value).
    """
    if not values:
        raise ValueError("values must be non-empty")
    if len(values) == 1:
        return (values[0], values[0])

    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(n_bootstrap):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    alpha = 1.0 - ci_level
    lower_idx = int((alpha / 2.0) * n_bootstrap)
    upper_idx = int((1.0 - alpha / 2.0) * n_bootstrap) - 1
    lower_idx = max(0, min(lower_idx, n_bootstrap - 1))
    upper_idx = max(0, min(upper_idx, n_bootstrap - 1))
    return (means[lower_idx], means[upper_idx])
