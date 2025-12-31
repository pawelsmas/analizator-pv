"""
Contract tests for annualization behavior (v1.5.0).

Tests verify:
- period_info.annualization_factor is 8760 / period_hours
- Full year (8760 hours) returns factor of 1.0
- Partial periods are scaled correctly
- Annualization factor is consistent across response fields
"""

import pytest
from ._api import post_json, load_smoke_payload


# -----------------------------------------------------------------------------
# Test: Annualization Factor Presence
# -----------------------------------------------------------------------------

class TestAnnualizationFactorPresence:
    """Test that annualization_factor is present in response."""

    def test_annualization_factor_in_period_info(self):
        """period_info should contain annualization_factor."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        assert "period_info" in result
        assert "annualization_factor" in result["period_info"]

    def test_annualization_factor_is_numeric(self):
        """annualization_factor should be a number."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        factor = result["period_info"]["annualization_factor"]
        assert isinstance(factor, (int, float))

    def test_annualization_factor_is_positive(self):
        """annualization_factor should be positive."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        factor = result["period_info"]["annualization_factor"]
        assert factor > 0


# -----------------------------------------------------------------------------
# Test: Annualization Factor Formula
# -----------------------------------------------------------------------------

class TestAnnualizationFactorFormula:
    """Test the annualization factor formula: 8760 / period_hours."""

    def test_annualization_factor_equals_formula(self):
        """annualization_factor should equal 8760 / period_hours."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        period_info = result["period_info"]
        period_hours = period_info["period_hours"]
        reported_factor = period_info["annualization_factor"]

        # Calculate expected factor
        is_full_year = period_info["is_full_year"]
        if is_full_year:
            expected_factor = 1.0
        else:
            expected_factor = 8760 / period_hours

        assert abs(reported_factor - expected_factor) < 0.0001, \
            f"Factor mismatch: {reported_factor} != {expected_factor}"

    def test_full_year_factor_is_one(self):
        """Full year (8760 hours) should have factor of 1.0."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        period_info = result["period_info"]
        if period_info["is_full_year"]:
            assert period_info["annualization_factor"] == 1.0


# -----------------------------------------------------------------------------
# Test: Period Info Consistency
# -----------------------------------------------------------------------------

class TestPeriodInfoConsistency:
    """Test period_info field consistency."""

    def test_period_days_equals_period_hours_div_24(self):
        """period_days should equal period_hours / 24."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        period_info = result["period_info"]
        expected_days = period_info["period_hours"] / 24
        actual_days = period_info["period_days"]

        assert abs(expected_days - actual_days) < 0.0001

    def test_is_full_year_when_period_ge_8760(self):
        """is_full_year should be True when period_hours >= 8760."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        period_info = result["period_info"]
        period_hours = period_info["period_hours"]
        is_full_year = period_info["is_full_year"]

        if period_hours >= 8760:
            assert is_full_year is True
        else:
            assert is_full_year is False

    def test_steps_times_step_minutes_equals_period_hours_times_60(self):
        """steps * step_minutes should equal period_hours * 60 (total minutes)."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        period_info = result["period_info"]
        if period_info.get("steps") and period_info.get("step_minutes"):
            total_minutes_from_steps = period_info["steps"] * period_info["step_minutes"]
            total_minutes_from_hours = period_info["period_hours"] * 60

            assert abs(total_minutes_from_steps - total_minutes_from_hours) < 1.0


# -----------------------------------------------------------------------------
# Test: Annualization Consistency Across Response
# -----------------------------------------------------------------------------

class TestAnnualizationConsistency:
    """Test annualization is consistent across all response fields."""

    def test_period_hours_consistent_with_load_array_length(self):
        """period_hours should be consistent with load array length."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        period_info = result["period_info"]
        steps = period_info.get("steps")
        step_minutes = period_info.get("step_minutes", 60)

        if steps is not None:
            # Load array length should match steps
            load_length = len(payload.get("load_kw", []))
            if load_length > 0:
                assert load_length == steps, \
                    f"Load length {load_length} != steps {steps}"


# -----------------------------------------------------------------------------
# Test: Partial Period Annualization
# -----------------------------------------------------------------------------

class TestPartialPeriodAnnualization:
    """Test annualization for partial periods (< 8760 hours)."""

    def test_partial_period_factor_greater_than_one(self):
        """Partial period (< 8760 hours) should have factor > 1."""
        # Create a 30-day payload
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Trim to 30 days (720 hours)
        if "load_kw" in payload and len(payload["load_kw"]) > 720:
            payload["load_kw"] = payload["load_kw"][:720]
        if "pv_kw" in payload and len(payload["pv_kw"]) > 720:
            payload["pv_kw"] = payload["pv_kw"][:720]

        result = post_json("/sizing", payload)
        period_info = result["period_info"]

        if period_info["period_hours"] < 8760:
            assert period_info["annualization_factor"] > 1.0
            assert period_info["is_full_year"] is False


# -----------------------------------------------------------------------------
# Test: Constants
# -----------------------------------------------------------------------------

class TestAnnualizationConstants:
    """Test annualization uses correct constants."""

    def test_uses_8760_hours_per_year(self):
        """Annualization should use 8760 hours per year (non-leap)."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Create exactly 1/12 of a year
        if "load_kw" in payload and len(payload["load_kw"]) >= 730:
            payload["load_kw"] = payload["load_kw"][:730]  # ~30.4 days
        if "pv_kw" in payload and len(payload["pv_kw"]) >= 730:
            payload["pv_kw"] = payload["pv_kw"][:730]

        result = post_json("/sizing", payload)
        period_info = result["period_info"]

        if period_info["period_hours"] == 730:
            expected_factor = 8760 / 730  # ~12.0
            actual_factor = period_info["annualization_factor"]
            assert abs(actual_factor - expected_factor) < 0.001
