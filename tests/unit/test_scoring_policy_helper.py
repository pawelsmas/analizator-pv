"""
Unit tests for scoring policy helper (v4.5.0 PR4).

Tests:
- Scoring by different objectives
- Near-optimal variant finding
- Tie-breaker application
- Full policy selection
"""

import sys
from pathlib import Path
import pytest

# Add services/bess-dispatch to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scoring_policy_helper import (
    ScoredVariant,
    score_by_objective,
    find_best_by_objective,
    find_near_optimal_variants,
    apply_tie_breaker,
    select_with_policy,
    rank_variants_by_objective,
)


def create_test_variants():
    """Create test variants for scoring tests."""
    return [
        ScoredVariant(
            variant_id="small_1h",
            power_kw=50.0,
            duration_h=1.0,
            energy_kwh=50.0,
            npv_pln=100000.0,
            irr_pct=15.0,
            payback_years=5.0,
            capex_pln=50000.0,
            self_consumption_rate=0.70,
            peak_reduction_kw=30.0,
            lcos_pln_per_mwh=300.0,
            resilience_score=0.90,
        ),
        ScoredVariant(
            variant_id="medium_2h",
            power_kw=50.0,
            duration_h=2.0,
            energy_kwh=100.0,
            npv_pln=98000.0,  # 2% worse NPV
            irr_pct=14.0,
            payback_years=5.5,
            capex_pln=80000.0,
            self_consumption_rate=0.85,  # Better self-consumption
            peak_reduction_kw=35.0,
            lcos_pln_per_mwh=280.0,  # Better LCOS
            resilience_score=0.95,
        ),
        ScoredVariant(
            variant_id="large_4h",
            power_kw=50.0,
            duration_h=4.0,
            energy_kwh=200.0,
            npv_pln=90000.0,  # 10% worse NPV
            irr_pct=12.0,
            payback_years=6.5,
            capex_pln=150000.0,
            self_consumption_rate=0.92,
            peak_reduction_kw=40.0,
            lcos_pln_per_mwh=320.0,
            resilience_score=0.98,
        ),
    ]


class TestScoreByObjective:
    """Tests for score_by_objective function."""

    def test_score_npv_maximize(self):
        """NPV scoring: higher is better."""
        variants = create_test_variants()
        scored = score_by_objective(variants, "npv")

        # small_1h has best NPV
        assert scored[0].scores["npv"] == 100.0
        # large_4h has worst NPV
        assert scored[2].scores["npv"] == 0.0

    def test_score_payback_minimize(self):
        """Payback scoring: lower is better."""
        variants = create_test_variants()
        scored = score_by_objective(variants, "payback")

        # small_1h has best payback (5 years)
        assert scored[0].scores["payback"] == 100.0
        # large_4h has worst payback (6.5 years)
        assert scored[2].scores["payback"] == 0.0

    def test_score_lcos_minimize(self):
        """LCOS scoring: lower is better."""
        variants = create_test_variants()
        scored = score_by_objective(variants, "lcos")

        # medium_2h has best LCOS (280)
        assert scored[1].scores["lcos"] == 100.0
        # large_4h has worst LCOS (320)
        assert scored[2].scores["lcos"] == 0.0

    def test_score_self_consumption_maximize(self):
        """Self-consumption scoring: higher is better."""
        variants = create_test_variants()
        scored = score_by_objective(variants, "self_consumption")

        # large_4h has best self-consumption (0.92)
        assert scored[2].scores["self_consumption"] == 100.0
        # small_1h has worst (0.70)
        assert scored[0].scores["self_consumption"] == 0.0


class TestFindBestByObjective:
    """Tests for find_best_by_objective function."""

    def test_find_best_npv(self):
        """Find variant with best NPV."""
        variants = create_test_variants()
        best = find_best_by_objective(variants, "npv")

        assert best.variant_id == "small_1h"

    def test_find_best_self_consumption(self):
        """Find variant with best self-consumption."""
        variants = create_test_variants()
        best = find_best_by_objective(variants, "self_consumption")

        assert best.variant_id == "large_4h"

    def test_find_best_lcos(self):
        """Find variant with best LCOS (lowest)."""
        variants = create_test_variants()
        best = find_best_by_objective(variants, "lcos")

        assert best.variant_id == "medium_2h"

    def test_empty_list_returns_none(self):
        """Empty variant list returns None."""
        best = find_best_by_objective([], "npv")
        assert best is None


class TestFindNearOptimalVariants:
    """Tests for find_near_optimal_variants function."""

    def test_find_near_optimal_5_percent(self):
        """Find variants within 5% of best NPV score."""
        variants = create_test_variants()
        near_optimal = find_near_optimal_variants(variants, "npv", tolerance_pct=5.0)

        # Score calculation: small_1h=100, medium_2h=80, large_4h=0
        # (because normalized over range 90k-100k)
        # 5% of 100 = 95 threshold, only small_1h passes
        variant_ids = [v.variant_id for v in near_optimal]

        assert "small_1h" in variant_ids
        # medium_2h score is 80, below 95 threshold
        assert len(near_optimal) == 1

    def test_find_near_optimal_25_percent(self):
        """Find variants within 25% of best NPV score."""
        variants = create_test_variants()
        near_optimal = find_near_optimal_variants(variants, "npv", tolerance_pct=25.0)

        # 25% of 100 = 75 threshold
        # small_1h=100, medium_2h=80 pass; large_4h=0 fails
        variant_ids = [v.variant_id for v in near_optimal]

        assert "small_1h" in variant_ids
        assert "medium_2h" in variant_ids
        assert len(near_optimal) == 2

    def test_find_near_optimal_zero_tolerance(self):
        """Zero tolerance returns only best."""
        variants = create_test_variants()
        near_optimal = find_near_optimal_variants(variants, "npv", tolerance_pct=0.0)

        assert len(near_optimal) == 1
        assert near_optimal[0].variant_id == "small_1h"


class TestApplyTieBreaker:
    """Tests for apply_tie_breaker function."""

    def test_tie_breaker_self_consumption(self):
        """Self-consumption tie-breaker prefers higher."""
        variants = create_test_variants()[:2]  # small_1h and medium_2h
        winner = apply_tie_breaker(variants, "self_consumption_rate")

        assert winner.variant_id == "medium_2h"  # 0.85 > 0.70

    def test_tie_breaker_payback(self):
        """Payback tie-breaker prefers lower."""
        variants = create_test_variants()[:2]
        winner = apply_tie_breaker(variants, "payback_years")

        assert winner.variant_id == "small_1h"  # 5.0 < 5.5

    def test_tie_breaker_duration(self):
        """Duration tie-breaker prefers longer."""
        variants = create_test_variants()[:2]
        winner = apply_tie_breaker(variants, "duration_h")

        assert winner.variant_id == "medium_2h"  # 2h > 1h

    def test_single_variant_returns_it(self):
        """Single variant returns that variant."""
        variants = [create_test_variants()[0]]
        winner = apply_tie_breaker(variants, "self_consumption_rate")

        assert winner.variant_id == "small_1h"


class TestSelectWithPolicy:
    """Tests for select_with_policy function."""

    def test_select_best_npv_no_tie_break_needed(self):
        """Select best NPV when clearly better."""
        variants = create_test_variants()

        # With 0% tolerance, should pick best NPV
        winner, meta = select_with_policy(
            variants,
            primary_objective="npv",
            tolerance_pct=0.0,
        )

        assert winner.variant_id == "small_1h"
        assert meta["is_near_optimal"] is False
        assert meta["reason_code"] == "npv_max"

    def test_select_with_tie_break(self):
        """Select using tie-breaker when near-optimal."""
        variants = create_test_variants()

        # With 25% tolerance, small_1h (score=100) and medium_2h (score=80) are near-optimal
        # Tie-breaker on self_consumption_rate should pick medium_2h (0.85 > 0.70)
        winner, meta = select_with_policy(
            variants,
            primary_objective="npv",
            tolerance_pct=25.0,  # Need 25% to include medium_2h
            tie_breakers=["self_consumption_rate"],
        )

        assert winner.variant_id == "medium_2h"
        assert meta["is_near_optimal"] is True
        assert meta["tie_breaker_used"] == "self_consumption_rate"
        assert meta["reason_code"] == "npv_near_optimal_tie_break"

    def test_select_with_min_npv_filter(self):
        """Filter by min_npv_pln constraint."""
        variants = create_test_variants()

        # Filter out large_4h (90k NPV)
        winner, meta = select_with_policy(
            variants,
            primary_objective="npv",
            min_npv_pln=95000.0,
        )

        assert winner.variant_id in ["small_1h", "medium_2h"]
        assert meta["filtered_by_min_npv"] == 1

    def test_select_empty_returns_none(self):
        """Empty list returns None."""
        winner, meta = select_with_policy([])

        assert winner is None
        assert meta["total_variants"] == 0

    def test_metadata_includes_counts(self):
        """Metadata includes variant counts."""
        variants = create_test_variants()

        winner, meta = select_with_policy(
            variants,
            primary_objective="npv",
            tolerance_pct=25.0,  # Use 25% to get 2 near-optimal
        )

        assert meta["total_variants"] == 3
        assert meta["near_optimal_count"] == 2  # small_1h and medium_2h


class TestRankVariantsByObjective:
    """Tests for rank_variants_by_objective function."""

    def test_rank_by_npv(self):
        """Rank variants by NPV."""
        variants = create_test_variants()
        ranked = rank_variants_by_objective(variants, "npv", top_n=3)

        assert len(ranked) == 3
        assert ranked[0][0].variant_id == "small_1h"
        assert ranked[0][1] == 1  # Rank 1
        assert ranked[1][0].variant_id == "medium_2h"
        assert ranked[1][1] == 2
        assert ranked[2][0].variant_id == "large_4h"
        assert ranked[2][1] == 3

    def test_rank_top_n_limits_results(self):
        """top_n limits returned results."""
        variants = create_test_variants()
        ranked = rank_variants_by_objective(variants, "npv", top_n=2)

        assert len(ranked) == 2

    def test_rank_empty_returns_empty(self):
        """Empty list returns empty."""
        ranked = rank_variants_by_objective([], "npv")

        assert ranked == []
