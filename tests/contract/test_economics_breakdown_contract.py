"""
Contract tests for economics_breakdown SSoT (v1.5.0).

Tests verify:
- economics_breakdown.totals_pln always present in dispatch_summary
- economics_breakdown.timeseries_pln only when include_economics_timeseries=True
- Sum invariant: sum(timeseries_pln[field]) == totals_pln[field]
- Totals match savings_breakdown fields
"""

import pytest
from ._api import post_json, load_smoke_payload


# -----------------------------------------------------------------------------
# Test: Economics Breakdown Presence
# -----------------------------------------------------------------------------

class TestEconomicsBreakdownPresence:
    """Test that economics_breakdown appears in response."""

    def test_economics_breakdown_present_in_dispatch_summary(self):
        """economics_breakdown should be present in dispatch_summary."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        variant = result["variants"][0]
        assert "dispatch_summary" in variant
        assert "economics_breakdown" in variant["dispatch_summary"]

    def test_totals_pln_always_present(self):
        """totals_pln should always be present."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        eb = result["variants"][0]["dispatch_summary"]["economics_breakdown"]
        assert "totals_pln" in eb
        assert eb["totals_pln"] is not None

    def test_timeseries_pln_absent_by_default(self):
        """timeseries_pln should be None when not requested."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        eb = result["variants"][0]["dispatch_summary"]["economics_breakdown"]
        assert eb["timeseries_pln"] is None

    def test_timeseries_pln_present_when_requested(self):
        """timeseries_pln should be present when include_economics_timeseries=True."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_economics_timeseries"] = True
        result = post_json("/sizing", payload)

        eb = result["variants"][0]["dispatch_summary"]["economics_breakdown"]
        assert eb["timeseries_pln"] is not None


# -----------------------------------------------------------------------------
# Test: Totals Structure
# -----------------------------------------------------------------------------

class TestEconomicsBreakdownTotalsStructure:
    """Test the structure of totals_pln."""

    def test_totals_has_required_fields(self):
        """totals_pln should have all required fields."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        totals = result["variants"][0]["dispatch_summary"]["economics_breakdown"]["totals_pln"]

        required_fields = [
            "energy_cost_baseline_pln",
            "energy_cost_project_pln",
            "energy_savings_pln",
            "export_revenue_pln",
            "capacity_fee_baseline_pln",
            "capacity_fee_project_pln",
            "capacity_fee_savings_pln",
            "demand_charge_baseline_pln",
            "demand_charge_project_pln",
            "demand_charge_savings_pln",
            "degradation_cost_pln",
        ]

        for field in required_fields:
            assert field in totals, f"Missing field: {field}"

    def test_totals_values_are_numeric(self):
        """All totals values should be numeric."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        totals = result["variants"][0]["dispatch_summary"]["economics_breakdown"]["totals_pln"]

        for key, value in totals.items():
            assert isinstance(value, (int, float)), f"{key} is not numeric: {type(value)}"


# -----------------------------------------------------------------------------
# Test: Timeseries Structure
# -----------------------------------------------------------------------------

class TestEconomicsBreakdownTimeseriesStructure:
    """Test the structure of timeseries_pln."""

    def test_timeseries_has_required_fields(self):
        """timeseries_pln should have required array fields."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_economics_timeseries"] = True
        result = post_json("/sizing", payload)

        ts = result["variants"][0]["dispatch_summary"]["economics_breakdown"]["timeseries_pln"]

        required_fields = [
            "energy_cost_baseline_pln",
            "energy_cost_project_pln",
            "export_revenue_pln",
        ]

        for field in required_fields:
            assert field in ts, f"Missing field: {field}"
            assert isinstance(ts[field], list), f"{field} should be a list"

    def test_timeseries_length_matches_period(self):
        """Timeseries arrays should match analysis period length."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_economics_timeseries"] = True
        result = post_json("/sizing", payload)

        ts = result["variants"][0]["dispatch_summary"]["economics_breakdown"]["timeseries_pln"]
        period_info = result["period_info"]

        expected_steps = period_info["steps"]

        assert len(ts["energy_cost_baseline_pln"]) == expected_steps
        assert len(ts["energy_cost_project_pln"]) == expected_steps
        assert len(ts["export_revenue_pln"]) == expected_steps


# -----------------------------------------------------------------------------
# Test: Sum Invariant
# -----------------------------------------------------------------------------

class TestEconomicsBreakdownSumInvariant:
    """Test the sum invariant: sum(timeseries) == totals."""

    def test_energy_cost_baseline_sum_invariant(self):
        """sum(energy_cost_baseline_pln) should equal totals.energy_cost_baseline_pln."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_economics_timeseries"] = True
        result = post_json("/sizing", payload)

        eb = result["variants"][0]["dispatch_summary"]["economics_breakdown"]
        totals = eb["totals_pln"]
        ts = eb["timeseries_pln"]

        ts_sum = sum(ts["energy_cost_baseline_pln"])
        expected = totals["energy_cost_baseline_pln"]

        assert abs(ts_sum - expected) < 0.01, f"Sum invariant failed: {ts_sum} != {expected}"

    def test_energy_cost_project_sum_invariant(self):
        """sum(energy_cost_project_pln) should equal totals.energy_cost_project_pln."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_economics_timeseries"] = True
        result = post_json("/sizing", payload)

        eb = result["variants"][0]["dispatch_summary"]["economics_breakdown"]
        totals = eb["totals_pln"]
        ts = eb["timeseries_pln"]

        ts_sum = sum(ts["energy_cost_project_pln"])
        expected = totals["energy_cost_project_pln"]

        assert abs(ts_sum - expected) < 0.01, f"Sum invariant failed: {ts_sum} != {expected}"

    def test_export_revenue_sum_invariant(self):
        """sum(export_revenue_pln) should equal totals.export_revenue_pln."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_economics_timeseries"] = True
        result = post_json("/sizing", payload)

        eb = result["variants"][0]["dispatch_summary"]["economics_breakdown"]
        totals = eb["totals_pln"]
        ts = eb["timeseries_pln"]

        ts_sum = sum(ts["export_revenue_pln"])
        expected = totals["export_revenue_pln"]

        assert abs(ts_sum - expected) < 0.01, f"Sum invariant failed: {ts_sum} != {expected}"


# -----------------------------------------------------------------------------
# Test: Energy Savings Consistency
# -----------------------------------------------------------------------------

class TestEconomicsBreakdownEnergySavings:
    """Test energy savings calculation consistency."""

    def test_energy_savings_equals_baseline_minus_project(self):
        """energy_savings_pln should equal baseline - project cost."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        totals = result["variants"][0]["dispatch_summary"]["economics_breakdown"]["totals_pln"]

        expected_savings = totals["energy_cost_baseline_pln"] - totals["energy_cost_project_pln"]
        actual_savings = totals["energy_savings_pln"]

        assert abs(expected_savings - actual_savings) < 0.01, \
            f"Energy savings mismatch: {expected_savings} != {actual_savings}"


# -----------------------------------------------------------------------------
# Test: Degradation Cost Consistency
# -----------------------------------------------------------------------------

class TestEconomicsBreakdownDegradation:
    """Test degradation cost consistency with savings_breakdown."""

    def test_degradation_cost_matches_savings_breakdown(self):
        """degradation_cost_pln should match savings_breakdown.degradation_cost_pln."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        result = post_json("/sizing", payload)

        variant = result["variants"][0]
        eb_degradation = variant["dispatch_summary"]["economics_breakdown"]["totals_pln"]["degradation_cost_pln"]
        sb_degradation = variant["savings_breakdown"]["degradation_cost_pln"]

        assert abs(eb_degradation - sb_degradation) < 0.01, \
            f"Degradation cost mismatch: {eb_degradation} != {sb_degradation}"
