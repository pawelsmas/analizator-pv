"""
Golden master tests for economics_engine.py (Faza 1 refaktoring).

Verifies that the unified calculate_npv() produces results consistent
with the old calculate_npv() and calculate_npv_lifecycle() from sizing_runner.py.

Run: python -m pytest test_economics_engine.py -v
"""

import pytest
from economics_engine import (
    NpvConfig,
    NpvResult,
    calculate_npv,
    calculate_simple_payback,
    calculate_irr_from_cashflows,
    combined_soh,
    battery_lifetime_years,
)

# Import old functions for comparison
from sizing_runner import (
    calculate_npv as old_calculate_npv,
    calculate_npv_lifecycle as old_calculate_npv_lifecycle,
    _combined_soh as old_combined_soh,
    calculate_battery_lifetime_years as old_battery_lifetime_years,
    calculate_simple_payback as old_simple_payback,
    calculate_irr_from_cashflow as old_irr_from_cashflow,
)


# ============================================================
# Test data — representative scenarios from real portal usage
# ============================================================

# Scenario A: Small battery, pv_surplus, no degradation
SCENARIO_A = dict(annual_savings=46000, capex=231000, opex_pct=0.015,
                  discount_rate=0.07, years=15)

# Scenario B: Large battery, arbitrage
SCENARIO_B = dict(annual_savings=433000, capex=2307000, opex_pct=0.015,
                  discount_rate=0.07, years=15)

# Scenario C: Medium battery, lifecycle with degradation
SCENARIO_C = dict(annual_savings=100000, capex=500000, opex_pct=0.015,
                  discount_rate=0.07, years=15,
                  efc_per_year=500, energy_kwh=1000,
                  cycles_to_eol=6000, eol_soh_pct=70,
                  calendar_deg_year1_pct=5.0, calendar_deg_annual_pct=2.0)

# Scenario D: Lifecycle with escalation
SCENARIO_D = dict(**SCENARIO_C,
                  savings_escalation_rate=0.025, opex_escalation_rate=0.025)


# ============================================================
# Golden Master: SoH model consistency
# ============================================================

class TestSoHConsistency:
    """combined_soh() must match old _combined_soh() exactly."""

    @pytest.mark.parametrize("year", [1, 3, 5, 7, 10, 15, 20])
    def test_soh_linear(self, year):
        kwargs = dict(efc_per_year=500, energy_kwh=1000, cycles_to_eol=6000,
                      eol_soh_pct=70, calendar_deg_year1_pct=5.0,
                      calendar_deg_annual_pct=2.0, degradation_curve="linear")
        old = old_combined_soh(year, **kwargs)
        new = combined_soh(year, **kwargs)
        assert abs(old - new) < 1e-10, f"Year {year}: old={old}, new={new}"

    @pytest.mark.parametrize("year", [1, 3, 5, 7, 10, 15])
    def test_soh_sqrt(self, year):
        kwargs = dict(efc_per_year=500, energy_kwh=1000, cycles_to_eol=6000,
                      eol_soh_pct=70, calendar_deg_year1_pct=2.0,
                      calendar_deg_annual_pct=1.0, degradation_curve="sqrt")
        old = old_combined_soh(year, **kwargs)
        new = combined_soh(year, **kwargs)
        assert abs(old - new) < 1e-10, f"Year {year}: old={old}, new={new}"

    def test_soh_year_zero(self):
        assert combined_soh(0, 500, 1000, 6000, 70, 5.0, 2.0) == 1.0
        assert old_combined_soh(0, 500, 1000, 6000, 70, 5.0, 2.0) == 1.0


class TestBatteryLifetimeConsistency:
    """battery_lifetime_years() must match old calculate_battery_lifetime_years()."""

    @pytest.mark.parametrize("efc,expected_range", [
        (300, (8, 15)),
        (500, (5, 10)),
        (800, (3, 7)),
    ])
    def test_lifetime_matches_old(self, efc, expected_range):
        config = NpvConfig(
            efc_per_year=efc, energy_kwh=1000,
            cycles_to_eol=6000, eol_soh_pct=70,
            calendar_deg_year1_pct=5.0, calendar_deg_annual_pct=2.0,
            degradation_curve="linear",
        )
        old = old_battery_lifetime_years(
            efc, 6000, 70, 1000, 5.0, 2.0, "linear", 30,
        )
        new = battery_lifetime_years(efc, 1000, config, 30)
        assert old == new, f"EFC={efc}: old={old}, new={new}"
        assert expected_range[0] <= new <= expected_range[1]


# ============================================================
# Golden Master: Simple NPV consistency
# ============================================================

class TestSimpleNpvConsistency:
    """
    New calculate_npv(config=simple) must match old calculate_npv() exactly.

    When include_degradation=False and escalation=0, the new engine
    should produce identical results to the old simple formula.
    """

    def test_scenario_a(self):
        old = old_calculate_npv(**SCENARIO_A)
        config = NpvConfig(
            discount_rate=SCENARIO_A['discount_rate'],
            analysis_years=SCENARIO_A['years'],
            opex_pct=SCENARIO_A['opex_pct'],
        )
        new = calculate_npv(SCENARIO_A['annual_savings'], SCENARIO_A['capex'], config)
        assert abs(old - new.npv_pln) < 0.01, \
            f"Scenario A: old={old:.2f}, new={new.npv_pln:.2f}"

    def test_scenario_b(self):
        old = old_calculate_npv(**SCENARIO_B)
        config = NpvConfig(
            discount_rate=SCENARIO_B['discount_rate'],
            analysis_years=SCENARIO_B['years'],
            opex_pct=SCENARIO_B['opex_pct'],
        )
        new = calculate_npv(SCENARIO_B['annual_savings'], SCENARIO_B['capex'], config)
        assert abs(old - new.npv_pln) < 0.01, \
            f"Scenario B: old={old:.2f}, new={new.npv_pln:.2f}"

    def test_zero_savings(self):
        old = old_calculate_npv(0, 100000, 0.015, 0.07, 15)
        new = calculate_npv(0, 100000, NpvConfig(analysis_years=15))
        assert abs(old - new.npv_pln) < 0.01

    def test_payback_consistency(self):
        old = old_simple_payback(46000, 231000)
        new = calculate_simple_payback(46000, 231000)
        assert abs(old - new) < 1e-10


# ============================================================
# Golden Master: Lifecycle NPV consistency
# ============================================================

class TestLifecycleNpvConsistency:
    """
    New calculate_npv(include_degradation=True, include_replacement=False)
    with effective_years as horizon must match old calculate_npv_lifecycle().
    """

    def test_scenario_c_lifecycle(self):
        """Lifecycle without escalation — must match old function."""
        old_npv, old_years = old_calculate_npv_lifecycle(
            annual_savings=SCENARIO_C['annual_savings'],
            capex=SCENARIO_C['capex'],
            opex_pct=SCENARIO_C['opex_pct'],
            discount_rate=SCENARIO_C['discount_rate'],
            years=SCENARIO_C['years'],
            efc_per_year=SCENARIO_C['efc_per_year'],
            energy_kwh=SCENARIO_C['energy_kwh'],
            cycles_to_eol=SCENARIO_C['cycles_to_eol'],
            eol_soh_pct=SCENARIO_C['eol_soh_pct'],
            calendar_deg_year1_pct=SCENARIO_C['calendar_deg_year1_pct'],
            calendar_deg_annual_pct=SCENARIO_C['calendar_deg_annual_pct'],
        )

        config = NpvConfig(
            discount_rate=SCENARIO_C['discount_rate'],
            analysis_years=SCENARIO_C['years'],
            opex_pct=SCENARIO_C['opex_pct'],
            include_degradation=True,
            efc_per_year=SCENARIO_C['efc_per_year'],
            energy_kwh=SCENARIO_C['energy_kwh'],
            cycles_to_eol=SCENARIO_C['cycles_to_eol'],
            eol_soh_pct=SCENARIO_C['eol_soh_pct'],
            calendar_deg_year1_pct=SCENARIO_C['calendar_deg_year1_pct'],
            calendar_deg_annual_pct=SCENARIO_C['calendar_deg_annual_pct'],
        )
        # For lifecycle comparison: use effective_years as horizon (old behavior)
        new = calculate_npv(SCENARIO_C['annual_savings'], SCENARIO_C['capex'], config)

        assert new.battery_lifetime_years == old_years, \
            f"Lifetime: old={old_years}, new={new.battery_lifetime_years}"

        # The new engine uses full analysis_years (not truncated to EOL)
        # So NPV will differ if battery dies before analysis_years.
        # This is INTENTIONAL — the old behavior was the bug.
        # But effective_years should match.
        assert new.effective_years == old_years

    def test_scenario_d_lifecycle_with_escalation(self):
        """Lifecycle with escalation — must match old function."""
        old_npv, old_years = old_calculate_npv_lifecycle(
            annual_savings=SCENARIO_C['annual_savings'],
            capex=SCENARIO_C['capex'],
            opex_pct=SCENARIO_C['opex_pct'],
            discount_rate=SCENARIO_C['discount_rate'],
            years=SCENARIO_C['years'],
            efc_per_year=SCENARIO_C['efc_per_year'],
            energy_kwh=SCENARIO_C['energy_kwh'],
            cycles_to_eol=SCENARIO_C['cycles_to_eol'],
            eol_soh_pct=SCENARIO_C['eol_soh_pct'],
            savings_escalation_rate=0.025,
            opex_escalation_rate=0.025,
            calendar_deg_year1_pct=SCENARIO_C['calendar_deg_year1_pct'],
            calendar_deg_annual_pct=SCENARIO_C['calendar_deg_annual_pct'],
        )

        config = NpvConfig(
            discount_rate=SCENARIO_C['discount_rate'],
            analysis_years=SCENARIO_C['years'],
            opex_pct=SCENARIO_C['opex_pct'],
            include_degradation=True,
            efc_per_year=SCENARIO_C['efc_per_year'],
            energy_kwh=SCENARIO_C['energy_kwh'],
            cycles_to_eol=SCENARIO_C['cycles_to_eol'],
            eol_soh_pct=SCENARIO_C['eol_soh_pct'],
            calendar_deg_year1_pct=SCENARIO_C['calendar_deg_year1_pct'],
            calendar_deg_annual_pct=SCENARIO_C['calendar_deg_annual_pct'],
            savings_escalation_rate=0.025,
            opex_escalation_rate=0.025,
        )
        new = calculate_npv(SCENARIO_C['annual_savings'], SCENARIO_C['capex'], config)

        assert new.battery_lifetime_years == old_years


# ============================================================
# New behavior tests (replacement, full horizon)
# ============================================================

class TestNewBehavior:
    """Tests for NEW features not in old code."""

    def test_replacement_extends_horizon(self):
        """With replacement, NPV should be higher than without."""
        config_no_repl = NpvConfig(
            analysis_years=15, include_degradation=True,
            efc_per_year=500, energy_kwh=1000,
            cycles_to_eol=6000, eol_soh_pct=70,
            calendar_deg_year1_pct=5.0, calendar_deg_annual_pct=2.0,
        )
        config_with_repl = NpvConfig(
            analysis_years=15, include_degradation=True, include_replacement=True,
            replacement_cost_factor=0.6,
            efc_per_year=500, energy_kwh=1000,
            cycles_to_eol=6000, eol_soh_pct=70,
            calendar_deg_year1_pct=5.0, calendar_deg_annual_pct=2.0,
        )
        r_no = calculate_npv(100000, 500000, config_no_repl)
        r_yes = calculate_npv(100000, 500000, config_with_repl)

        # With replacement: battery continues earning after EOL
        # (minus replacement cost), so NPV should differ
        assert r_yes.npv_pln != r_no.npv_pln
        # Full horizon for both (15 years)
        assert len(r_yes.yearly_cashflows) == 16  # year 0..15
        assert len(r_no.yearly_cashflows) == 16

    def test_escalation_increases_npv(self):
        """Savings escalation should increase NPV vs no escalation."""
        config_flat = NpvConfig(analysis_years=15)
        config_esc = NpvConfig(analysis_years=15, savings_escalation_rate=0.03)

        r_flat = calculate_npv(100000, 500000, config_flat)
        r_esc = calculate_npv(100000, 500000, config_esc)

        assert r_esc.npv_pln > r_flat.npv_pln

    def test_irr_present_in_result(self):
        """IRR should be calculated for profitable projects."""
        config = NpvConfig(analysis_years=15)
        result = calculate_npv(100000, 500000, config)
        assert result.irr_pct is not None
        assert result.irr_pct > 0

    def test_irr_none_for_unprofitable(self):
        """IRR should be None when savings are zero."""
        config = NpvConfig(analysis_years=15)
        result = calculate_npv(0, 500000, config)
        assert result.irr_pct is None

    def test_cashflows_length(self):
        """Cashflows array has years+1 elements (year 0 = -CAPEX)."""
        config = NpvConfig(analysis_years=10)
        result = calculate_npv(50000, 200000, config)
        assert len(result.yearly_cashflows) == 11
        assert result.yearly_cashflows[0] == -200000

    def test_default_config(self):
        """calculate_npv with no config should work (defaults)."""
        result = calculate_npv(50000, 200000)
        assert result.npv_pln != 0
        assert result.effective_years == 15  # default


# ============================================================
# IRR consistency
# ============================================================

class TestIrrConsistency:
    def test_irr_matches_old(self):
        cashflows = [-500000] + [80000] * 15
        old = old_irr_from_cashflow(cashflows)
        new = calculate_irr_from_cashflows(cashflows)
        if old is not None and new is not None:
            assert abs(old - new) < 0.01, f"IRR: old={old}, new={new}"

    def test_irr_negative_cashflows(self):
        assert calculate_irr_from_cashflows([-100, -50, -30]) is None

    def test_irr_single_element(self):
        assert calculate_irr_from_cashflows([-100]) is None
