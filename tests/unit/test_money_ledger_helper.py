"""
Unit tests for money_ledger_helper (v1.9.0).

Tests verify:
- compute_money_ledger creates proper MoneyLedger structure
- Annualization works correctly
- Delta calculations are correct
- calculate_total() method works as expected
"""

import pytest
import sys
import os

# Add services/bess-dispatch to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from models import (
    MoneyLedger,
    MoneyLedgerTotalsPln,
    SavingsBreakdown,
    EconomicsBreakdown,
    EconomicsTotalsPln,
)
from money_ledger_helper import compute_money_ledger, _annualize


class TestMoneyLedgerTotalsPln:
    """Tests for MoneyLedgerTotalsPln model."""

    def test_calculate_total_basic(self):
        """Test calculate_total sums costs and subtracts revenue."""
        totals = MoneyLedgerTotalsPln(
            import_energy_cost_pln=1000.0,
            export_revenue_pln=200.0,
            other_fees_pln=50.0,
            capacity_fee_pln=100.0,
            demand_charge_pln=75.0,
            unserved_penalty_pln=0.0,
            degradation_cost_pln=25.0,
        )

        result = totals.calculate_total()

        # 1000 + 50 + 100 + 75 + 0 + 25 - 200 = 1050
        assert result == 1050.0

    def test_calculate_total_high_revenue(self):
        """Test calculate_total with revenue higher than costs."""
        totals = MoneyLedgerTotalsPln(
            import_energy_cost_pln=100.0,
            export_revenue_pln=500.0,  # High export revenue
            other_fees_pln=0.0,
            capacity_fee_pln=0.0,
            demand_charge_pln=0.0,
            unserved_penalty_pln=0.0,
            degradation_cost_pln=0.0,
        )

        result = totals.calculate_total()

        # 100 - 500 = -400 (negative = net revenue)
        assert result == -400.0

    def test_calculate_total_zero_values(self):
        """Test calculate_total with all zeros."""
        totals = MoneyLedgerTotalsPln()
        result = totals.calculate_total()
        assert result == 0.0


class TestAnnualize:
    """Tests for _annualize helper function."""

    def test_annualize_with_factor_2(self):
        """Test annualization with factor 2 (half year data)."""
        period = MoneyLedgerTotalsPln(
            import_energy_cost_pln=1000.0,
            export_revenue_pln=200.0,
            other_fees_pln=50.0,
            capacity_fee_pln=100.0,
            demand_charge_pln=75.0,
            unserved_penalty_pln=10.0,
            degradation_cost_pln=25.0,
            total_cost_pln=1060.0,  # Precalculated
        )

        annual = _annualize(period, 2.0)

        assert annual.import_energy_cost_pln == 2000.0
        assert annual.export_revenue_pln == 400.0
        assert annual.other_fees_pln == 100.0
        assert annual.capacity_fee_pln == 200.0
        assert annual.demand_charge_pln == 150.0
        assert annual.unserved_penalty_pln == 20.0
        assert annual.degradation_cost_pln == 50.0
        assert annual.total_cost_pln == 2120.0

    def test_annualize_with_factor_1(self):
        """Test annualization with factor 1 (full year)."""
        period = MoneyLedgerTotalsPln(
            import_energy_cost_pln=1000.0,
            export_revenue_pln=200.0,
            total_cost_pln=800.0,
        )

        annual = _annualize(period, 1.0)

        assert annual.import_energy_cost_pln == 1000.0
        assert annual.export_revenue_pln == 200.0
        assert annual.total_cost_pln == 800.0


class TestComputeMoneyLedger:
    """Tests for compute_money_ledger function."""

    def test_compute_with_economics_breakdown(self):
        """Test compute_money_ledger with full economics_breakdown."""
        savings = SavingsBreakdown(
            energy_savings_pln=500.0,
            capacity_fee_savings_pln=100.0,
            demand_charge_savings_pln=50.0,
            degradation_cost_pln=-20.0,  # Negative = cost
            unserved_load_penalty_pln=-10.0,  # Negative = penalty
            baseline_export_revenue_pln=100.0,
            project_export_revenue_pln=300.0,  # BESS enables more export
            net_savings_pln=520.0,
        )

        economics = EconomicsBreakdown(
            totals_pln=EconomicsTotalsPln(
                energy_cost_baseline_pln=1000.0,
                energy_cost_project_pln=500.0,
                energy_cost_savings_pln=500.0,
                capacity_fee_baseline_pln=200.0,
                capacity_fee_project_pln=100.0,
                capacity_fee_savings_pln=100.0,
                demand_charge_baseline_pln=150.0,
                demand_charge_project_pln=100.0,
                demand_charge_savings_pln=50.0,
            )
        )

        ledger = compute_money_ledger(
            savings_breakdown=savings,
            economics_breakdown=economics,
            period_hours=8760,
            annualization_factor=1.0,
        )

        # Baseline period checks
        assert ledger.baseline_period.import_energy_cost_pln == 1000.0
        assert ledger.baseline_period.export_revenue_pln == 100.0
        assert ledger.baseline_period.capacity_fee_pln == 200.0
        assert ledger.baseline_period.demand_charge_pln == 150.0

        # Project period checks
        assert ledger.project_period.import_energy_cost_pln == 500.0
        assert ledger.project_period.export_revenue_pln == 300.0
        assert ledger.project_period.capacity_fee_pln == 100.0
        assert ledger.project_period.demand_charge_pln == 100.0
        assert ledger.project_period.degradation_cost_pln == 20.0  # abs() applied
        assert ledger.project_period.unserved_penalty_pln == 10.0  # abs() applied

        # Full year
        assert ledger.is_full_year is True
        assert ledger.period_hours == 8760

    def test_compute_with_half_year_data(self):
        """Test compute_money_ledger with 4380 hours (half year)."""
        savings = SavingsBreakdown(
            energy_savings_pln=250.0,
            baseline_export_revenue_pln=50.0,
            project_export_revenue_pln=150.0,
            net_savings_pln=250.0,
        )

        economics = EconomicsBreakdown(
            totals_pln=EconomicsTotalsPln(
                energy_cost_baseline_pln=500.0,
                energy_cost_project_pln=250.0,
                energy_cost_savings_pln=250.0,
            )
        )

        ledger = compute_money_ledger(
            savings_breakdown=savings,
            economics_breakdown=economics,
            period_hours=4380,
            annualization_factor=2.0,
        )

        # Period values
        assert ledger.baseline_period.import_energy_cost_pln == 500.0
        assert ledger.project_period.import_energy_cost_pln == 250.0

        # Annual values (doubled)
        assert ledger.baseline_annual.import_energy_cost_pln == 1000.0
        assert ledger.project_annual.import_energy_cost_pln == 500.0

        # Not full year
        assert ledger.is_full_year is False
        assert ledger.period_hours == 4380

    def test_compute_without_economics_breakdown(self):
        """Test compute_money_ledger fallback when no economics_breakdown."""
        savings = SavingsBreakdown(
            energy_savings_pln=500.0,
            arbitrage_savings_pln=100.0,
            capacity_fee_savings_pln=100.0,
            demand_charge_savings_pln=50.0,
            baseline_export_revenue_pln=100.0,
            project_export_revenue_pln=300.0,
            net_savings_pln=550.0,
        )

        ledger = compute_money_ledger(
            savings_breakdown=savings,
            economics_breakdown=None,  # No breakdown
            period_hours=8760,
        )

        # Should still produce valid structure
        assert ledger.baseline_period is not None
        assert ledger.project_period is not None
        assert ledger.delta_period_pln is not None

        # Fallback uses savings as baseline cost approximation
        assert ledger.baseline_period.import_energy_cost_pln == 600.0  # energy + arbitrage
        assert ledger.baseline_period.export_revenue_pln == 100.0

    def test_delta_calculation(self):
        """Test that delta = baseline - project."""
        savings = SavingsBreakdown(
            energy_savings_pln=500.0,
            baseline_export_revenue_pln=100.0,
            project_export_revenue_pln=300.0,
            net_savings_pln=300.0,
        )

        economics = EconomicsBreakdown(
            totals_pln=EconomicsTotalsPln(
                energy_cost_baseline_pln=1000.0,
                energy_cost_project_pln=500.0,
            )
        )

        ledger = compute_money_ledger(
            savings_breakdown=savings,
            economics_breakdown=economics,
            period_hours=8760,
        )

        # Delta import cost = baseline - project = 1000 - 500 = 500
        assert ledger.delta_period_pln.import_energy_cost_pln == 500.0

        # Delta export = project - baseline = 300 - 100 = 200 (gain)
        assert ledger.delta_period_pln.export_revenue_pln == 200.0

    def test_auto_annualization_factor(self):
        """Test that annualization_factor is auto-calculated from period_hours."""
        savings = SavingsBreakdown(
            energy_savings_pln=250.0,
            baseline_export_revenue_pln=50.0,
            project_export_revenue_pln=150.0,
            net_savings_pln=250.0,
        )

        economics = EconomicsBreakdown(
            totals_pln=EconomicsTotalsPln(
                energy_cost_baseline_pln=500.0,
                energy_cost_project_pln=250.0,
            )
        )

        # Don't pass annualization_factor, let it calculate from period_hours
        ledger = compute_money_ledger(
            savings_breakdown=savings,
            economics_breakdown=economics,
            period_hours=4380,  # Half year
            # annualization_factor not passed, defaults to 1.0 but will be recalculated
        )

        # 8760 / 4380 = 2.0
        # Annual should be 2x period
        assert ledger.baseline_annual.import_energy_cost_pln == 1000.0  # 500 * 2
        assert ledger.project_annual.import_energy_cost_pln == 500.0   # 250 * 2
