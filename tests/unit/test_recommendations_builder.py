"""
Unit tests for recommendations builder (v4.5.0 PR5).

Tests:
- Building single recommendation
- Building recommendations for all objectives
- Grouping by variant
- Consensus variant finding
- Full response building
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scoring_policy_helper import ScoredVariant
from recommendations_builder import (
    build_recommendation_for_objective,
    build_recommendations_for_all_objectives,
    group_recommendations_by_variant,
    get_consensus_variant,
    build_recommendation_summary,
    build_full_recommendations_response,
)
from models import RecommendationPolicy


def create_test_variants():
    """Create test variants."""
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
            npv_pln=95000.0,
            irr_pct=14.0,
            payback_years=5.5,
            capex_pln=80000.0,
            self_consumption_rate=0.85,
            peak_reduction_kw=35.0,
            lcos_pln_per_mwh=280.0,
            resilience_score=0.95,
        ),
        ScoredVariant(
            variant_id="large_4h",
            power_kw=50.0,
            duration_h=4.0,
            energy_kwh=200.0,
            npv_pln=85000.0,
            irr_pct=12.0,
            payback_years=6.5,
            capex_pln=150000.0,
            self_consumption_rate=0.92,
            peak_reduction_kw=40.0,
            lcos_pln_per_mwh=320.0,
            resilience_score=0.98,
        ),
    ]


class TestBuildRecommendationForObjective:
    """Tests for build_recommendation_for_objective."""

    def test_builds_npv_recommendation(self):
        """Build NPV recommendation."""
        variant = create_test_variants()[0]
        meta = {"is_near_optimal": False, "tie_breaker_used": None}

        rec = build_recommendation_for_objective(variant, "npv", meta)

        assert rec.objective == "npv"
        assert rec.variant == "small_1h"
        assert rec.reason_code == "npv_max"
        assert rec.reason_metric == "npv_pln"
        assert rec.reason_value == 100000.0
        assert rec.reason_unit == "PLN"
        assert rec.is_near_optimal is False

    def test_builds_near_optimal_recommendation(self):
        """Build near-optimal recommendation with tie-breaker."""
        variant = create_test_variants()[1]
        meta = {"is_near_optimal": True, "tie_breaker_used": "self_consumption_rate"}

        rec = build_recommendation_for_objective(variant, "npv", meta)

        assert rec.is_near_optimal is True
        assert rec.tie_breaker_used == "self_consumption_rate"
        assert rec.reason_code == "npv_near_optimal_tie_break"

    def test_builds_lcos_recommendation(self):
        """Build LCOS recommendation (minimize)."""
        variant = create_test_variants()[1]  # Best LCOS
        meta = {"is_near_optimal": False}

        rec = build_recommendation_for_objective(variant, "lcos", meta)

        assert rec.objective == "lcos"
        assert rec.reason_code == "lcos_min"
        assert rec.reason_metric == "lcos_pln_per_mwh"
        assert rec.reason_unit == "PLN/MWh"


class TestBuildRecommendationsForAllObjectives:
    """Tests for build_recommendations_for_all_objectives."""

    def test_builds_for_default_objectives(self):
        """Build recommendations for default objectives."""
        variants = create_test_variants()

        recs = build_recommendations_for_all_objectives(variants)

        # Should have recommendations for default objectives
        objectives = [r.objective for r in recs]
        assert "npv" in objectives
        assert "self_consumption" in objectives
        assert "payback" in objectives

    def test_builds_for_custom_objectives(self):
        """Build recommendations for custom objectives."""
        variants = create_test_variants()

        recs = build_recommendations_for_all_objectives(
            variants,
            objectives=["npv", "lcos"]
        )

        assert len(recs) == 2
        objectives = [r.objective for r in recs]
        assert "npv" in objectives
        assert "lcos" in objectives

    def test_empty_variants_returns_empty(self):
        """Empty variants returns empty list."""
        recs = build_recommendations_for_all_objectives([])
        assert recs == []

    def test_uses_policy_for_tie_breaking(self):
        """Uses provided policy for tie-breaking."""
        variants = create_test_variants()
        policy = RecommendationPolicy(
            near_optimal_tolerance_pct=50.0,  # Very wide tolerance
            tie_breakers=["duration_h"],
        )

        recs = build_recommendations_for_all_objectives(
            variants,
            objectives=["npv"],
            policy=policy,
        )

        # With 50% tolerance and duration tie-breaker, large_4h might win
        assert len(recs) == 1


class TestGroupRecommendationsByVariant:
    """Tests for group_recommendations_by_variant."""

    def test_groups_correctly(self):
        """Group recommendations by variant."""
        variants = create_test_variants()
        recs = build_recommendations_for_all_objectives(
            variants,
            objectives=["npv", "payback", "self_consumption", "lcos"]
        )

        grouped = group_recommendations_by_variant(recs)

        # Should have variant IDs as keys
        assert isinstance(grouped, dict)
        for variant_id, objectives in grouped.items():
            assert isinstance(objectives, list)

    def test_empty_recommendations(self):
        """Empty recommendations returns empty dict."""
        grouped = group_recommendations_by_variant([])
        assert grouped == {}


class TestGetConsensusVariant:
    """Tests for get_consensus_variant."""

    def test_finds_most_recommended(self):
        """Find variant recommended by most objectives."""
        variants = create_test_variants()

        # With default objectives, small_1h likely wins NPV and payback
        recs = build_recommendations_for_all_objectives(
            variants,
            objectives=["npv", "payback", "self_consumption"]
        )

        consensus = get_consensus_variant(recs)
        assert consensus is not None

    def test_empty_returns_none(self):
        """Empty recommendations returns None."""
        consensus = get_consensus_variant([])
        assert consensus is None


class TestBuildRecommendationSummary:
    """Tests for build_recommendation_summary."""

    def test_summary_has_all_fields(self):
        """Summary contains all required fields."""
        variants = create_test_variants()
        recs = build_recommendations_for_all_objectives(variants)

        summary = build_recommendation_summary(recs)

        assert "total_objectives" in summary
        assert "recommendations_by_variant" in summary
        assert "consensus_variant" in summary
        assert "unique_variants" in summary

    def test_summary_counts(self):
        """Summary counts are correct."""
        variants = create_test_variants()
        recs = build_recommendations_for_all_objectives(
            variants,
            objectives=["npv", "lcos", "self_consumption"]
        )

        summary = build_recommendation_summary(recs)

        assert summary["total_objectives"] == 3
        assert summary["unique_variants"] >= 1


class TestBuildFullRecommendationsResponse:
    """Tests for build_full_recommendations_response."""

    def test_response_structure(self):
        """Response has correct structure."""
        variants = create_test_variants()

        response = build_full_recommendations_response(variants)

        assert response.recommendations is not None
        assert response.summary is not None
        assert response.policy_used is not None

    def test_response_to_dict(self):
        """Response converts to dict correctly."""
        variants = create_test_variants()

        response = build_full_recommendations_response(variants)
        data = response.to_dict()

        assert "recommendations" in data
        assert "summary" in data
        assert "policy_used" in data
        assert isinstance(data["recommendations"], list)

    def test_policy_echoed(self):
        """Policy is echoed in response."""
        variants = create_test_variants()
        policy = RecommendationPolicy(
            near_optimal_tolerance_pct=10.0,
            tie_breakers=["duration_h"],
        )

        response = build_full_recommendations_response(
            variants,
            policy=policy
        )

        assert response.policy_used["near_optimal_tolerance_pct"] == 10.0
        assert response.policy_used["tie_breakers"] == ["duration_h"]
