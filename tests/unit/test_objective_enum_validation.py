"""
Unit tests for objective enum and v4.5.0 driver models validation.

Tests:
- OptimizationObjective enum values
- OptimizationProfile enum values
- RecommendationPolicy validation (tie-breakers, tolerance)
- VariantSpace validation (grid size limits)
- DriverRecommendation model structure
- Objective aliases in request_normalizer
"""

import sys
from pathlib import Path
import pytest

# Add services/bess-dispatch to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestOptimizationObjectiveEnum:
    """Tests for OptimizationObjective enum."""

    def test_all_objectives_exist(self):
        """All expected objective values are defined."""
        from models import OptimizationObjective

        expected = {
            "npv", "irr", "payback", "self_consumption", "self_consumption_rate",
            "peak_reduction", "efc_utilization", "lcos", "lcoe", "resilience"
        }
        actual = {obj.value for obj in OptimizationObjective}

        assert expected == actual, f"Missing: {expected - actual}, Extra: {actual - expected}"

    def test_objective_is_string_enum(self):
        """OptimizationObjective inherits from str and Enum."""
        from models import OptimizationObjective

        assert isinstance(OptimizationObjective.NPV, str)
        assert OptimizationObjective.NPV == "npv"

    def test_objective_from_string(self):
        """Can create enum from string value."""
        from models import OptimizationObjective

        obj = OptimizationObjective("npv")
        assert obj == OptimizationObjective.NPV

        obj = OptimizationObjective("lcos")
        assert obj == OptimizationObjective.LCOS

    def test_invalid_objective_raises_valueerror(self):
        """Invalid string raises ValueError."""
        from models import OptimizationObjective

        with pytest.raises(ValueError):
            OptimizationObjective("invalid")

    def test_objective_comparison(self):
        """Enum values can be compared as strings."""
        from models import OptimizationObjective

        assert OptimizationObjective.NPV == "npv"
        assert OptimizationObjective.LCOS != "lcoe"  # Different values


class TestOptimizationProfileEnum:
    """Tests for OptimizationProfile enum."""

    def test_all_profiles_exist(self):
        """All expected profile values are defined."""
        from models import OptimizationProfile

        expected = {
            "balanced", "commercial_peak_shaving", "pv_self_consumption",
            "arbitrage", "resilience_backup"
        }
        actual = {p.value for p in OptimizationProfile}

        assert expected == actual

    def test_profile_is_string_enum(self):
        """OptimizationProfile inherits from str."""
        from models import OptimizationProfile

        assert isinstance(OptimizationProfile.BALANCED, str)
        assert OptimizationProfile.BALANCED == "balanced"


class TestRecommendationPolicyValidation:
    """Tests for RecommendationPolicy model validation."""

    def test_default_values(self):
        """Default RecommendationPolicy has expected values."""
        from models import RecommendationPolicy

        policy = RecommendationPolicy()

        assert policy.near_optimal_tolerance_pct == 5.0
        assert policy.tie_breakers == ["self_consumption_rate", "payback_years", "peak_reduction_kw"]
        assert policy.min_npv_pln is None

    def test_valid_tie_breakers_accepted(self):
        """Valid tie-breaker names are accepted."""
        from models import RecommendationPolicy

        policy = RecommendationPolicy(
            tie_breakers=["npv_pln", "irr_pct", "duration_h"]
        )
        assert len(policy.tie_breakers) == 3

    def test_invalid_tie_breaker_rejected(self):
        """Invalid tie-breaker name raises validation error."""
        from models import RecommendationPolicy
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            RecommendationPolicy(tie_breakers=["invalid_metric"])

        assert "Invalid tie-breaker" in str(exc_info.value)

    def test_tolerance_bounds(self):
        """Tolerance must be 0-50%."""
        from models import RecommendationPolicy
        from pydantic import ValidationError

        # Valid bounds
        RecommendationPolicy(near_optimal_tolerance_pct=0.0)
        RecommendationPolicy(near_optimal_tolerance_pct=50.0)

        # Invalid bounds
        with pytest.raises(ValidationError):
            RecommendationPolicy(near_optimal_tolerance_pct=-1.0)

        with pytest.raises(ValidationError):
            RecommendationPolicy(near_optimal_tolerance_pct=51.0)

    def test_min_npv_constraint(self):
        """min_npv_pln can be set to filter variants."""
        from models import RecommendationPolicy

        policy = RecommendationPolicy(min_npv_pln=50000.0)
        assert policy.min_npv_pln == 50000.0


class TestVariantSpaceValidation:
    """Tests for VariantSpace model validation."""

    def test_default_durations(self):
        """Default duration candidates are [1, 2, 4]."""
        from models import VariantSpace

        vs = VariantSpace()
        assert vs.duration_h_candidates == [1.0, 2.0, 4.0]
        assert vs.max_variants == 60

    def test_custom_power_and_duration(self):
        """Custom power x duration grid is accepted."""
        from models import VariantSpace

        vs = VariantSpace(
            power_kw_candidates=[50.0, 100.0, 150.0],
            duration_h_candidates=[1.0, 2.0]
        )
        assert len(vs.power_kw_candidates) == 3
        assert len(vs.duration_h_candidates) == 2

    def test_grid_size_within_limit(self):
        """Grid size <= max_variants is accepted."""
        from models import VariantSpace

        # 3 powers x 2 durations = 6 variants < 60
        vs = VariantSpace(
            power_kw_candidates=[50.0, 100.0, 150.0],
            duration_h_candidates=[1.0, 2.0],
            max_variants=60
        )
        assert vs is not None

    def test_grid_size_exceeds_limit_rejected(self):
        """Grid size > max_variants raises validation error."""
        from models import VariantSpace
        from pydantic import ValidationError

        # 10 powers x 10 durations = 100 variants > 50
        with pytest.raises(ValidationError) as exc_info:
            VariantSpace(
                power_kw_candidates=[i * 10.0 for i in range(1, 11)],
                duration_h_candidates=[float(i) for i in range(1, 11)],
                max_variants=50
            )

        assert "exceeds max_variants" in str(exc_info.value)

    def test_max_variants_bounds(self):
        """max_variants must be 1-200."""
        from models import VariantSpace
        from pydantic import ValidationError

        # Valid bounds
        VariantSpace(max_variants=1)
        VariantSpace(max_variants=200)

        # Invalid bounds
        with pytest.raises(ValidationError):
            VariantSpace(max_variants=0)

        with pytest.raises(ValidationError):
            VariantSpace(max_variants=201)


class TestDriverRecommendationModel:
    """Tests for DriverRecommendation model structure."""

    def test_required_fields(self):
        """All required fields must be provided."""
        from models import DriverRecommendation

        rec = DriverRecommendation(
            objective="npv",
            variant="medium",
            reason_code="npv_max",
            reason_metric="npv_pln",
            reason_value=150000.0,
            reason_unit="PLN"
        )

        assert rec.objective == "npv"
        assert rec.variant == "medium"
        assert rec.reason_code == "npv_max"
        assert rec.is_near_optimal is False
        assert rec.tie_breaker_used is None

    def test_near_optimal_with_tie_breaker(self):
        """Near-optimal recommendation with tie-breaker."""
        from models import DriverRecommendation

        rec = DriverRecommendation(
            objective="npv",
            variant="large",
            reason_code="npv_near_optimal_tie_break",
            reason_metric="self_consumption_rate",
            reason_value=0.85,
            reason_unit="ratio",
            is_near_optimal=True,
            tie_breaker_used="self_consumption_rate"
        )

        assert rec.is_near_optimal is True
        assert rec.tie_breaker_used == "self_consumption_rate"


class TestDurationSweepPoint:
    """Tests for DurationSweepPoint model."""

    def test_required_fields(self):
        """duration_h and npv_pln are required."""
        from models import DurationSweepPoint

        point = DurationSweepPoint(
            duration_h=2.0,
            npv_pln=120000.0
        )

        assert point.duration_h == 2.0
        assert point.npv_pln == 120000.0
        assert point.payback_years is None  # Optional

    def test_all_fields(self):
        """All optional fields can be set."""
        from models import DurationSweepPoint

        point = DurationSweepPoint(
            duration_h=4.0,
            npv_pln=180000.0,
            payback_years=5.2,
            self_consumption_rate=0.82,
            lcos_pln_per_mwh=350.0,
            power_kw=100.0
        )

        assert point.payback_years == 5.2
        assert point.self_consumption_rate == 0.82
        assert point.lcos_pln_per_mwh == 350.0


class TestMarginalMetrics:
    """Tests for MarginalMetrics model."""

    def test_all_fields_optional(self):
        """All marginal metrics are optional."""
        from models import MarginalMetrics

        mm = MarginalMetrics()
        assert mm.marginal_npv_pln_per_added_kwh is None
        assert mm.marginal_net_savings_pln_per_added_kwh is None
        assert mm.marginal_self_consumption_pct_per_added_kwh is None

    def test_with_values(self):
        """Marginal values can be set."""
        from models import MarginalMetrics

        mm = MarginalMetrics(
            marginal_npv_pln_per_added_kwh=250.0,
            marginal_net_savings_pln_per_added_kwh=45.0,
            marginal_self_consumption_pct_per_added_kwh=0.002
        )

        assert mm.marginal_npv_pln_per_added_kwh == 250.0


class TestRecommendedReasonCodeEnum:
    """Tests for extended RecommendedReasonCode enum."""

    def test_new_reason_codes_exist(self):
        """v4.5.0 reason codes are defined."""
        from models import RecommendedReasonCode

        new_codes = {"irr_max", "lcos_min", "resilience_max", "npv_near_optimal_tie_break"}

        actual = {code.value for code in RecommendedReasonCode}

        for code in new_codes:
            assert code in actual, f"Missing reason code: {code}"


class TestObjectiveAliases:
    """Tests for objective alias normalization."""

    def test_lcoe_alias_exists(self):
        """LCOE maps to LCOS in aliases."""
        from request_normalizer import OBJECTIVE_ALIASES

        assert "lcoe" in OBJECTIVE_ALIASES
        assert OBJECTIVE_ALIASES["lcoe"] == "lcos"

    def test_self_consumption_rate_alias_exists(self):
        """self_consumption_rate maps to self_consumption."""
        from request_normalizer import OBJECTIVE_ALIASES

        assert "self_consumption_rate" in OBJECTIVE_ALIASES
        assert OBJECTIVE_ALIASES["self_consumption_rate"] == "self_consumption"
