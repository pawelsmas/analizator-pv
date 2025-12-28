"""
Unit tests for Scoring Engine
=============================
Tests cover:
1. Threshold interpolation (piecewise scoring)
2. Normalization to baseline
3. Contract length < horizon (savings=0 after N)
4. Missing data handling (exclude & rescale weights)
5. Weight profiles
6. Full scoring flow
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring.models import (
    OfferInputs,
    ScoringParameters,
    WeightProfile,
    ThresholdRule,
    ThresholdConfig,
    ProfileType,
    WEIGHT_PROFILES,
)
from scoring.engine import ScoringEngine, score_offers


class TestThresholdRule:
    """Test piecewise threshold scoring"""

    def test_below_minimum_threshold(self):
        """Values below minimum threshold get minimum points"""
        rule = ThresholdRule(
            thresholds=[0.0, 0.10, 0.20],
            points=[0, 10, 20]
        )
        assert rule.score(-0.05) == 0
        assert rule.score(0.0) == 0

    def test_above_maximum_threshold(self):
        """Values above maximum threshold get maximum points (saturated)"""
        rule = ThresholdRule(
            thresholds=[0.0, 0.10, 0.20],
            points=[0, 10, 20]
        )
        assert rule.score(0.20) == 20
        assert rule.score(0.50) == 20
        assert rule.score(1.0) == 20

    def test_exact_threshold_values(self):
        """Exact threshold values get exact points"""
        rule = ThresholdRule(
            thresholds=[0.0, 0.10, 0.20, 0.30],
            points=[0, 5, 10, 15]
        )
        assert rule.score(0.0) == 0
        assert rule.score(0.10) == 5
        assert rule.score(0.20) == 10
        assert rule.score(0.30) == 15

    def test_linear_interpolation(self):
        """Values between thresholds are linearly interpolated"""
        rule = ThresholdRule(
            thresholds=[0.0, 0.10, 0.20],
            points=[0, 10, 20]
        )
        # Midpoint between 0 and 0.10
        assert rule.score(0.05) == 5
        # Midpoint between 0.10 and 0.20
        assert rule.score(0.15) == 15
        # 25% between 0.10 and 0.20
        assert rule.score(0.125) == 12.5

    def test_non_linear_point_progression(self):
        """Points don't have to be linear with thresholds"""
        rule = ThresholdRule(
            thresholds=[0.0, 0.50, 1.0],
            points=[0, 5, 20]  # Faster growth in second half
        )
        assert rule.score(0.25) == 2.5  # 50% between 0 and 5
        assert rule.score(0.75) == 12.5  # 50% between 5 and 20


class TestNormalizationToBaseline:
    """Test that KPIs are normalized to baseline costs"""

    def test_npv_rel_calculation(self):
        """NPV_rel = NPV_savings / PV(baseline)"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,  # 100k/year
            project_cost_by_year_base=[70000] * 25,  # 70k/year = 30k savings/year
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        params = ScoringParameters(
            horizon_years=25,
            discount_rate=0.07,
        )
        engine = ScoringEngine(params)
        result = engine._score_single_offer(offer)

        # NPV savings should be ~30k * annuity factor
        # Annuity factor @ 7% for 25 years ≈ 11.65
        # NPV_savings ≈ 30000 * 11.65 ≈ 349,500
        # PV_baseline ≈ 100000 * 11.65 ≈ 1,165,000
        # NPV_rel ≈ 349,500 / 1,165,000 ≈ 0.30

        assert result.kpi_rel.npv_rel_base > 0.25
        assert result.kpi_rel.npv_rel_base < 0.35

    def test_year1_rel_calculation(self):
        """Year1_rel = Year1_savings / Year1_baseline"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[60000] * 25,  # 40% savings
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        engine = ScoringEngine()
        result = engine._score_single_offer(offer)

        # Year1 savings = 100000 - 60000 = 40000
        # Year1_rel = 40000 / 100000 = 0.40
        assert result.kpi_rel.year1_rel_base == pytest.approx(0.40, rel=0.01)


class TestContractLengthHandling:
    """Test that contract length < horizon sets savings=0 after contract ends"""

    def test_short_contract_zeros_savings(self):
        """After contract ends, savings should be zero"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            contract_years=10,  # Only 10 years
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[70000] * 25,
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        params = ScoringParameters(horizon_years=25)
        engine = ScoringEngine(params)
        result = engine._score_single_offer(offer)

        # Savings should be 30k for years 1-10, 0 for years 11-25
        kpi = result.kpi_raw
        assert len(kpi.savings_by_year_base) == 25

        # First 10 years have savings
        for i in range(10):
            assert kpi.savings_by_year_base[i] == pytest.approx(30000, rel=0.01)

        # Years 11-25 have no savings
        for i in range(10, 25):
            assert kpi.savings_by_year_base[i] == pytest.approx(0, abs=1)

    def test_short_contract_generates_warning_flag(self):
        """Short contract should generate a warning flag"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            contract_years=10,
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[70000] * 25,
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        params = ScoringParameters(horizon_years=25)
        engine = ScoringEngine(params)
        result = engine._score_single_offer(offer)

        contract_flags = [f for f in result.flags if f.code == "CONTRACT_SHORT"]
        assert len(contract_flags) == 1
        assert "10 lat" in contract_flags[0].message
        assert "25 lat" in contract_flags[0].message


class TestMissingDataHandling:
    """Test that missing data excludes KPI and rescales weights"""

    def test_missing_co2_data(self):
        """Missing CO2 data should exclude ESG and rescale weights"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[70000] * 25,
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
            co2_baseline_tons_per_year=None,  # Missing
            co2_project_tons_per_year=None,
        )

        engine = ScoringEngine()
        result = engine._score_single_offer(offer)

        # CO2 should be in missing KPIs
        assert "co2_rel" in result.completeness.missing_kpis

        # ESG bucket should be 0 (redistributed)
        assert result.bucket_scores.esg == 0

        # There should be an info flag
        esg_flags = [f for f in result.flags if f.code == "ESG_MISSING"]
        assert len(esg_flags) == 1

    def test_with_co2_data(self):
        """When CO2 data is present, ESG bucket should be scored"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[70000] * 25,
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
            co2_baseline_tons_per_year=1000,
            co2_project_tons_per_year=300,  # 70% reduction
        )

        engine = ScoringEngine()
        result = engine._score_single_offer(offer)

        # CO2 should not be in missing KPIs
        assert "co2_rel" not in result.completeness.missing_kpis

        # ESG bucket should have score > 0
        assert result.bucket_scores.esg > 0

        # CO2_rel should be 0.70
        assert result.kpi_rel.co2_rel == pytest.approx(0.70, rel=0.01)


class TestWeightProfiles:
    """Test that different weight profiles affect scoring"""

    def test_cfo_profile_emphasizes_value(self):
        """CFO profile should weight Value bucket highest"""
        profile = WEIGHT_PROFILES[ProfileType.CFO]
        assert profile.value_weight >= profile.robustness_weight
        assert profile.value_weight >= profile.tech_weight
        assert profile.value_weight >= profile.esg_weight

    def test_esg_profile_emphasizes_esg(self):
        """ESG profile should weight ESG bucket highest"""
        profile = WEIGHT_PROFILES[ProfileType.ESG]
        assert profile.esg_weight >= profile.value_weight
        assert profile.esg_weight >= profile.robustness_weight

    def test_operations_profile_emphasizes_tech(self):
        """Operations profile should weight Tech bucket highly"""
        profile = WEIGHT_PROFILES[ProfileType.OPERATIONS]
        assert profile.tech_weight >= profile.value_weight

    def test_different_profiles_give_different_scores(self):
        """Same offer should get different scores with different profiles"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[70000] * 25,
            auto_consumption_pct=0.95,  # Very high - good for tech
            coverage_pct=0.4,  # Lower coverage
            co2_baseline_tons_per_year=1000,
            co2_project_tons_per_year=200,  # 80% reduction - good for ESG
        )

        # Score with CFO profile
        params_cfo = ScoringParameters(profile=WEIGHT_PROFILES[ProfileType.CFO])
        result_cfo = ScoringEngine(params_cfo)._score_single_offer(offer)

        # Score with ESG profile
        params_esg = ScoringParameters(profile=WEIGHT_PROFILES[ProfileType.ESG])
        result_esg = ScoringEngine(params_esg)._score_single_offer(offer)

        # ESG profile should score this offer higher (due to high CO2 reduction)
        # and different bucket distributions
        assert result_cfo.bucket_scores.value != result_esg.bucket_scores.value
        assert result_cfo.bucket_scores.esg != result_esg.bucket_scores.esg


class TestFullScoringFlow:
    """Test complete scoring workflow with multiple offers"""

    def test_multiple_offers_ranking(self):
        """Multiple offers should be ranked by total score"""
        offers = [
            OfferInputs(
                offer_id="A",
                name="Oferta A",
                baseline_cost_by_year=[100000] * 25,
                project_cost_by_year_base=[80000] * 25,  # 20% savings
                auto_consumption_pct=0.70,
                coverage_pct=0.50,
            ),
            OfferInputs(
                offer_id="B",
                name="Oferta B",
                baseline_cost_by_year=[100000] * 25,
                project_cost_by_year_base=[60000] * 25,  # 40% savings - better
                auto_consumption_pct=0.85,
                coverage_pct=0.70,
            ),
            OfferInputs(
                offer_id="C",
                name="Oferta C",
                baseline_cost_by_year=[100000] * 25,
                project_cost_by_year_base=[90000] * 25,  # 10% savings - worst
                auto_consumption_pct=0.60,
                coverage_pct=0.30,
            ),
        ]

        response = score_offers(offers)

        # Should have 3 results
        assert len(response.results) == 3

        # Should be ranked
        assert response.results[0].rank == 1
        assert response.results[1].rank == 2
        assert response.results[2].rank == 3

        # B should be ranked highest (40% savings + high tech)
        assert response.results[0].offer_id == "B"

        # Scores should be descending
        assert response.results[0].total_score >= response.results[1].total_score
        assert response.results[1].total_score >= response.results[2].total_score

    def test_comparison_reasons_for_winner(self):
        """Winner should have comparison reasons"""
        offers = [
            OfferInputs(
                offer_id="A",
                name="Oferta A",
                baseline_cost_by_year=[100000] * 25,
                project_cost_by_year_base=[60000] * 25,
                auto_consumption_pct=0.85,
                coverage_pct=0.70,
            ),
            OfferInputs(
                offer_id="B",
                name="Oferta B",
                baseline_cost_by_year=[100000] * 25,
                project_cost_by_year_base=[80000] * 25,
                auto_consumption_pct=0.70,
                coverage_pct=0.50,
            ),
        ]

        response = score_offers(offers)

        # Winner should have "Lider rankingu" in reasons
        winner = response.results[0]
        leader_reasons = [r for r in winner.reasons if "Lider" in r]
        assert len(leader_reasons) >= 1


class TestConservativeScenario:
    """Test conservative scenario calculations"""

    def test_conservative_scenario_generated(self):
        """Conservative scenario should be auto-generated if not provided"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[70000] * 25,  # 30k savings
            project_cost_by_year_cons=None,  # Auto-generate
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        params = ScoringParameters(
            conservative_yield_factor=0.90,  # -10% yield
            conservative_price_factor=0.90,  # -10% prices
        )
        engine = ScoringEngine(params)
        result = engine._score_single_offer(offer)

        # Conservative savings should be 30k * 0.9 * 0.9 = 24.3k
        expected_cons_savings = 30000 * 0.9 * 0.9

        assert result.kpi_raw.savings_by_year_cons[0] == pytest.approx(
            expected_cons_savings, rel=0.01
        )

    def test_robustness_delta_calculation(self):
        """Robustness delta = NPV_cons / NPV_base"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[70000] * 25,
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        params = ScoringParameters(
            conservative_yield_factor=0.90,
            conservative_price_factor=0.90,
        )
        engine = ScoringEngine(params)
        result = engine._score_single_offer(offer)

        # Robustness delta should be ~0.81 (0.9 * 0.9)
        assert result.kpi_rel.robustness_delta == pytest.approx(0.81, rel=0.02)


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_zero_baseline_costs(self):
        """Handle zero baseline costs gracefully (no division by zero)"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[0] * 25,
            project_cost_by_year_base=[0] * 25,
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        engine = ScoringEngine()
        result = engine._score_single_offer(offer)

        # Should not crash, relative KPIs should be 0
        assert result.kpi_rel.npv_rel_base == 0
        assert result.kpi_rel.year1_rel_base == 0

    def test_negative_savings(self):
        """Handle negative savings (project costs more than baseline)"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 25,
            project_cost_by_year_base=[120000] * 25,  # Worse than baseline!
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        engine = ScoringEngine()
        result = engine._score_single_offer(offer)

        # Should have negative NPV savings
        assert result.kpi_raw.npv_savings_base < 0

        # Should have NPV_NEGATIVE flag
        npv_flags = [f for f in result.flags if f.code == "NPV_NEGATIVE"]
        assert len(npv_flags) == 1

    def test_single_year_horizon(self):
        """Handle minimum horizon of 5 years"""
        offer = OfferInputs(
            offer_id="test",
            name="Test",
            baseline_cost_by_year=[100000] * 5,
            project_cost_by_year_base=[70000] * 5,
            auto_consumption_pct=0.8,
            coverage_pct=0.5,
        )

        params = ScoringParameters(horizon_years=5)
        engine = ScoringEngine(params)
        result = engine._score_single_offer(offer)

        # Should complete without error
        assert result.total_score >= 0
        assert len(result.kpi_raw.savings_by_year_base) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
