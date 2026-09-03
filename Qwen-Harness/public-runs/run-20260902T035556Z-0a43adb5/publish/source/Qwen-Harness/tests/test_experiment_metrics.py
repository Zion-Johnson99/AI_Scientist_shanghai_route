"""Unit tests for experiment metrics: Jaccard, Spearman, variance, constraint pass rate."""

import math
import sys
from pathlib import Path

import pytest

# Ensure the source package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qwen_harness.experiment.metrics import (
    jaccard_top_k,
    spearman_rank_correlation,
    dimension_variance,
    constraint_pass_rate,
    median,
    interquartile_range,
    bootstrap_confidence_interval,
)


# ---------------------------------------------------------------------------
# Jaccard top-k
# ---------------------------------------------------------------------------


class TestJaccardTopK:
    """Tests for jaccard_top_k function."""

    def test_identical_sets(self):
        """Identical top-k sets should yield Jaccard = 1.0."""
        a = ["r1", "r2", "r3", "r4", "r5"]
        b = ["r1", "r2", "r3", "r4", "r5"]
        assert jaccard_top_k(a, b, k=5) == pytest.approx(1.0)

    def test_completely_disjoint(self):
        """Completely disjoint sets should yield Jaccard = 0.0."""
        a = ["r1", "r2", "r3", "r4", "r5"]
        b = ["r6", "r7", "r8", "r9", "r10"]
        assert jaccard_top_k(a, b, k=5) == pytest.approx(0.0)

    def test_partial_overlap(self):
        """Partial overlap: 3 shared out of 7 union elements."""
        a = ["r1", "r2", "r3", "r4", "r5"]
        b = ["r3", "r4", "r5", "r6", "r7"]
        # intersection = {r3, r4, r5} size 3; union = {r1..r7} size 7
        assert jaccard_top_k(a, b, k=5) == pytest.approx(3.0 / 7.0)

    def test_empty_both(self):
        """Both empty lists should return 1.0 (vacuous truth)."""
        assert jaccard_top_k([], [], k=5) == pytest.approx(1.0)

    def test_one_empty(self):
        """One empty list should return 0.0."""
        a = ["r1", "r2", "r3"]
        assert jaccard_top_k(a, [], k=5) == pytest.approx(0.0)
        assert jaccard_top_k([], a, k=5) == pytest.approx(0.0)

    def test_single_element_same(self):
        """Single element sets that match."""
        assert jaccard_top_k(["r1"], ["r1"], k=5) == pytest.approx(1.0)

    def test_single_element_different(self):
        """Single element sets that differ."""
        assert jaccard_top_k(["r1"], ["r2"], k=5) == pytest.approx(0.0)

    def test_k_larger_than_list(self):
        """When k exceeds list length, use all available elements."""
        a = ["r1", "r2"]
        b = ["r1", "r2", "r3"]
        # top-2 of a = {r1, r2}; top-2 of b = {r1, r2}
        assert jaccard_top_k(a, b, k=5) == pytest.approx(1.0)

    def test_order_independence(self):
        """Jaccard is set-based, order within top-k should not matter."""
        a = ["r1", "r2", "r3", "r4", "r5"]
        b = ["r5", "r4", "r3", "r2", "r1"]
        assert jaccard_top_k(a, b, k=5) == pytest.approx(1.0)

    def test_duplicates_in_input(self):
        """Duplicates in input should be treated as set (deduplicated)."""
        a = ["r1", "r1", "r2", "r3", "r4"]
        b = ["r1", "r2", "r3", "r4", "r5"]
        # set(a) = {r1, r2, r3, r4}, set(b) = {r1, r2, r3, r4, r5}
        # intersection = 4, union = 5
        assert jaccard_top_k(a, b, k=5) == pytest.approx(4.0 / 5.0)


# ---------------------------------------------------------------------------
# Spearman rank correlation
# ---------------------------------------------------------------------------


class TestSpearmanRankCorrelation:
    """Tests for spearman_rank_correlation function."""

    def test_perfect_positive(self):
        """Identical rankings should yield rho = 1.0."""
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert spearman_rank_correlation(a, b) == pytest.approx(1.0)

    def test_perfect_negative(self):
        """Perfectly reversed rankings should yield rho = -1.0."""
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert spearman_rank_correlation(a, b) == pytest.approx(-1.0)

    def test_single_element(self):
        """Single element: correlation is trivially 1.0."""
        assert spearman_rank_correlation([1.0], [1.0]) == pytest.approx(1.0)

    def test_two_elements_same_order(self):
        """Two elements in same order."""
        assert spearman_rank_correlation([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)

    def test_two_elements_reversed(self):
        """Two elements in reversed order."""
        assert spearman_rank_correlation([1.0, 2.0], [2.0, 1.0]) == pytest.approx(-1.0)

    def test_empty_lists(self):
        """Empty lists should raise ValueError."""
        with pytest.raises(ValueError):
            spearman_rank_correlation([], [])

    def test_length_mismatch(self):
        """Mismatched lengths should raise ValueError."""
        with pytest.raises(ValueError):
            spearman_rank_correlation([1.0, 2.0], [1.0])

    def test_with_ties(self):
        """Tied values should use average rank method."""
        # a: ranks [1.5, 1.5, 3, 4, 5]
        # b: ranks [1, 2, 3, 4, 5]
        a = [10.0, 10.0, 30.0, 40.0, 50.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0]
        rho = spearman_rank_correlation(a, b)
        # With ties, rho should be close to 1 but not exactly 1
        assert 0.9 < rho <= 1.0

    def test_known_value(self):
        """Known Spearman value for a specific case."""
        # Scores: a = [100, 90, 80, 70, 60], b = [95, 85, 75, 65, 55]
        # Both have same rank order -> rho = 1.0
        a = [100.0, 90.0, 80.0, 70.0, 60.0]
        b = [95.0, 85.0, 75.0, 65.0, 55.0]
        assert spearman_rank_correlation(a, b) == pytest.approx(1.0)

    def test_partial_correlation(self):
        """Partial correlation should be between -1 and 1."""
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [1.0, 3.0, 2.0, 5.0, 4.0]
        rho = spearman_rank_correlation(a, b)
        assert -1.0 <= rho <= 1.0
        # Ranks a: [1,2,3,4,5], ranks b: [1,3,2,5,4]
        # d = [0, -1, 1, -1, 1], d^2 = [0, 1, 1, 1, 1] = 4
        # rho = 1 - 6*4/(5*(25-1)) = 1 - 24/120 = 0.8
        assert rho == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Dimension variance
# ---------------------------------------------------------------------------


class TestDimensionVariance:
    """Tests for dimension_variance function."""

    def test_zero_variance(self):
        """All identical values should yield variance = 0."""
        values = [50.0, 50.0, 50.0, 50.0]
        assert dimension_variance(values) == pytest.approx(0.0)

    def test_known_variance(self):
        """Known variance for simple case."""
        # [1, 2, 3, 4, 5]: mean=3, var = (4+1+0+1+4)/5 = 2.0 (population)
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert dimension_variance(values) == pytest.approx(2.0)

    def test_single_element(self):
        """Single element should yield variance = 0."""
        assert dimension_variance([42.0]) == pytest.approx(0.0)

    def test_empty_list(self):
        """Empty list should raise ValueError."""
        with pytest.raises(ValueError):
            dimension_variance([])

    def test_two_elements(self):
        """Two elements: population variance."""
        # [0, 10]: mean=5, var = (25+25)/2 = 25
        assert dimension_variance([0.0, 10.0]) == pytest.approx(25.0)

    def test_large_values(self):
        """Large values should not cause overflow."""
        values = [1e6, 1e6 + 1, 1e6 + 2]
        var = dimension_variance(values)
        assert var == pytest.approx(2.0 / 3.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Constraint pass rate
# ---------------------------------------------------------------------------


class TestConstraintPassRate:
    """Tests for constraint_pass_rate function."""

    def test_all_pass(self):
        """All candidates pass -> rate = 1.0."""
        results = [True, True, True, True, True]
        assert constraint_pass_rate(results) == pytest.approx(1.0)

    def test_none_pass(self):
        """No candidates pass -> rate = 0.0."""
        results = [False, False, False]
        assert constraint_pass_rate(results) == pytest.approx(0.0)

    def test_partial_pass(self):
        """Some pass, some fail."""
        results = [True, False, True, False, True]
        assert constraint_pass_rate(results) == pytest.approx(0.6)

    def test_empty_list(self):
        """Empty list should raise ValueError."""
        with pytest.raises(ValueError):
            constraint_pass_rate([])

    def test_single_pass(self):
        """Single passing candidate."""
        assert constraint_pass_rate([True]) == pytest.approx(1.0)

    def test_single_fail(self):
        """Single failing candidate."""
        assert constraint_pass_rate([False]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Statistical helpers: median, IQR, bootstrap
# ---------------------------------------------------------------------------


class TestMedian:
    """Tests for median function."""

    def test_odd_count(self):
        assert median([3.0, 1.0, 2.0]) == pytest.approx(2.0)

    def test_even_count(self):
        assert median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)

    def test_single(self):
        assert median([7.0]) == pytest.approx(7.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            median([])


class TestInterquartileRange:
    """Tests for interquartile_range function."""

    def test_known_iqr(self):
        # Data: [1, 2, 3, 4, 5, 6, 7, 8]
        # Q1 = median([1,2,3,4]) = 2.5, Q3 = median([5,6,7,8]) = 6.5
        # IQR = 4.0
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        assert interquartile_range(data) == pytest.approx(4.0)

    def test_single_element(self):
        """Single element: IQR = 0."""
        assert interquartile_range([5.0]) == pytest.approx(0.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            interquartile_range([])


class TestBootstrapConfidenceInterval:
    """Tests for bootstrap_confidence_interval function."""

    def test_reproducible_with_seed(self):
        """Same seed should produce same interval."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        lo1, hi1 = bootstrap_confidence_interval(data, seed=1234)
        lo2, hi2 = bootstrap_confidence_interval(data, seed=1234)
        assert lo1 == lo2
        assert hi1 == hi2

    def test_different_seed_may_differ(self):
        """Different seeds may produce different intervals (not guaranteed but likely)."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        lo1, hi1 = bootstrap_confidence_interval(data, seed=1234)
        lo2, hi2 = bootstrap_confidence_interval(data, seed=5678)
        # They might be the same by chance, but interval should be valid
        assert lo1 <= hi1
        assert lo2 <= hi2

    def test_interval_bounds(self):
        """Interval should be within data range."""
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        lo, hi = bootstrap_confidence_interval(data, seed=1234)
        assert lo >= min(data)
        assert hi <= max(data)
        assert lo <= hi

    def test_single_element(self):
        """Single element: interval should be [val, val]."""
        lo, hi = bootstrap_confidence_interval([5.0], seed=1234)
        assert lo == pytest.approx(5.0)
        assert hi == pytest.approx(5.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            bootstrap_confidence_interval([], seed=1234)

    def test_identical_values(self):
        """All identical values: interval should be [val, val]."""
        data = [3.0, 3.0, 3.0, 3.0, 3.0]
        lo, hi = bootstrap_confidence_interval(data, seed=1234)
        assert lo == pytest.approx(3.0)
        assert hi == pytest.approx(3.0)
