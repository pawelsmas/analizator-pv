"""
Unit tests for determinism_helper module.

v1.6.0: Tests deterministic tie-breaking for variant selection.
"""

import sys
from pathlib import Path
from dataclasses import dataclass

# Add services/bess-dispatch to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from determinism_helper import (
    variant_sort_key,
    select_best_variant_deterministic,
    scores_are_equal,
    SCORE_EPSILON,
)


@dataclass
class MockVariant:
    """Mock variant for testing."""
    name: str
    score: float
    npv: float
    capex: float
    is_feasible: bool = True


def _score(v): return v.score
def _npv(v): return v.npv
def _capex(v): return v.capex
def _name(v): return v.name


class TestScoresAreEqual:
    """Tests for scores_are_equal function."""

    def test_equal_scores(self):
        assert scores_are_equal(100.0, 100.0) is True

    def test_very_close_scores(self):
        assert scores_are_equal(100.0, 100.0 + 1e-10) is True

    def test_different_scores(self):
        assert scores_are_equal(100.0, 100.1) is False

    def test_custom_epsilon(self):
        assert scores_are_equal(100.0, 100.001, epsilon=0.01) is True
        assert scores_are_equal(100.0, 100.02, epsilon=0.01) is False


class TestVariantSortKey:
    """Tests for variant_sort_key function."""

    def test_sort_key_order(self):
        v = MockVariant(name="medium", score=90.0, npv=50000.0, capex=100000.0)
        key = variant_sort_key(v, _score, _npv, _capex, _name)

        # Should return (-score, -npv, capex, name)
        assert key == (-90.0, -50000.0, 100000.0, "medium")

    def test_sorts_by_score_first(self):
        v1 = MockVariant(name="a", score=90.0, npv=50000.0, capex=100000.0)
        v2 = MockVariant(name="b", score=80.0, npv=60000.0, capex=80000.0)

        key1 = variant_sort_key(v1, _score, _npv, _capex, _name)
        key2 = variant_sort_key(v2, _score, _npv, _capex, _name)

        # v1 should come first (higher score = lower key due to negation)
        assert key1 < key2


class TestSelectBestVariantDeterministic:
    """Tests for select_best_variant_deterministic function."""

    def test_empty_list(self):
        result = select_best_variant_deterministic([], _score, _npv, _capex, _name)
        assert result is None

    def test_single_variant(self):
        variants = [MockVariant(name="small", score=90.0, npv=50000.0, capex=100000.0)]
        result = select_best_variant_deterministic(variants, _score, _npv, _capex, _name)
        assert result == 0

    def test_selects_highest_score(self):
        variants = [
            MockVariant(name="small", score=80.0, npv=50000.0, capex=100000.0),
            MockVariant(name="medium", score=90.0, npv=40000.0, capex=150000.0),
            MockVariant(name="large", score=70.0, npv=60000.0, capex=80000.0),
        ]
        result = select_best_variant_deterministic(variants, _score, _npv, _capex, _name)
        assert result == 1  # medium has highest score

    def test_tie_break_by_npv(self):
        """When scores are equal, higher NPV should win."""
        variants = [
            MockVariant(name="a", score=90.0, npv=50000.0, capex=100000.0),
            MockVariant(name="b", score=90.0, npv=60000.0, capex=100000.0),  # Higher NPV
            MockVariant(name="c", score=90.0, npv=40000.0, capex=100000.0),
        ]
        result = select_best_variant_deterministic(variants, _score, _npv, _capex, _name)
        assert result == 1  # b has highest NPV

    def test_tie_break_by_capex(self):
        """When scores and NPV are equal, lower CAPEX should win."""
        variants = [
            MockVariant(name="a", score=90.0, npv=50000.0, capex=120000.0),
            MockVariant(name="b", score=90.0, npv=50000.0, capex=80000.0),  # Lower CAPEX
            MockVariant(name="c", score=90.0, npv=50000.0, capex=150000.0),
        ]
        result = select_best_variant_deterministic(variants, _score, _npv, _capex, _name)
        assert result == 1  # b has lowest CAPEX

    def test_tie_break_by_name(self):
        """When everything else is equal, alphabetical name wins."""
        variants = [
            MockVariant(name="medium", score=90.0, npv=50000.0, capex=100000.0),
            MockVariant(name="small", score=90.0, npv=50000.0, capex=100000.0),
            MockVariant(name="large", score=90.0, npv=50000.0, capex=100000.0),
        ]
        result = select_best_variant_deterministic(variants, _score, _npv, _capex, _name)
        assert result == 2  # large comes first alphabetically

    def test_with_filter(self):
        """Filter should exclude non-matching variants."""
        variants = [
            MockVariant(name="a", score=90.0, npv=50000.0, capex=100000.0, is_feasible=False),
            MockVariant(name="b", score=80.0, npv=60000.0, capex=80000.0, is_feasible=True),
            MockVariant(name="c", score=70.0, npv=70000.0, capex=60000.0, is_feasible=True),
        ]
        filter_fn = lambda v: v.is_feasible
        result = select_best_variant_deterministic(
            variants, _score, _npv, _capex, _name, filter_fn
        )
        assert result == 1  # b is highest scoring feasible variant

    def test_filter_excludes_all(self):
        """Filter excluding all variants should return None."""
        variants = [
            MockVariant(name="a", score=90.0, npv=50000.0, capex=100000.0, is_feasible=False),
            MockVariant(name="b", score=80.0, npv=60000.0, capex=80000.0, is_feasible=False),
        ]
        filter_fn = lambda v: v.is_feasible
        result = select_best_variant_deterministic(
            variants, _score, _npv, _capex, _name, filter_fn
        )
        assert result is None

    def test_deterministic_with_identical_variants(self):
        """Identical variants should always select the same one."""
        # Run multiple times to ensure determinism
        variants = [
            MockVariant(name="small", score=90.0, npv=50000.0, capex=100000.0),
            MockVariant(name="medium", score=90.0, npv=50000.0, capex=100000.0),
            MockVariant(name="large", score=90.0, npv=50000.0, capex=100000.0),
        ]

        results = set()
        for _ in range(10):
            result = select_best_variant_deterministic(
                variants, _score, _npv, _capex, _name
            )
            results.add(result)

        # Should always be the same result
        assert len(results) == 1
        assert results.pop() == 2  # "large" alphabetically first
