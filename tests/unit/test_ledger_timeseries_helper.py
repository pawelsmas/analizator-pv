"""
Unit tests for ledger_timeseries_helper.py (v2.0.0 PR3).

Tests verify:
- Per-step cost calculations from energy and prices
- Sum invariant validation
- Ledger vs MoneyLedger reconciliation
"""

import pytest
import sys
import os

# Add service path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch')))

from ledger_timeseries_helper import (
    generate_ledger_timeseries,
    validate_ledger_vs_money_ledger,
)
from models import PriceTimeseriesPlnPerMwh, MoneyLedgerTotalsPln


class TestGenerateLedgerTimeseries:
    """Tests for generate_ledger_timeseries function."""

    def test_basic_generation(self):
        """Generate basic ledger timeseries from energy and prices."""
        grid_import_kwh = [10.0, 20.0, 30.0]  # 60 kWh total
        grid_export_kwh = [5.0, 10.0, 15.0]   # 30 kWh total

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0, 400.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        assert ledger.steps == 3
        assert len(ledger.import_cost_pln) == 3
        assert len(ledger.export_revenue_pln) == 3

    def test_import_cost_calculation(self):
        """Verify import cost calculation: energy_kwh * price_pln_mwh / 1000."""
        grid_import_kwh = [100.0]  # 100 kWh
        grid_export_kwh = [0.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],  # 800 PLN/MWh
            export_price_pln_per_mwh=[400.0],
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        # 100 kWh * 800 PLN/MWh / 1000 = 80 PLN
        assert ledger.import_cost_pln[0] == 80.0
        assert ledger.sum_import_cost_pln == 80.0

    def test_export_revenue_calculation(self):
        """Verify export revenue calculation."""
        grid_import_kwh = [0.0]
        grid_export_kwh = [50.0]  # 50 kWh

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],
            export_price_pln_per_mwh=[400.0],  # 400 PLN/MWh
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        # 50 kWh * 400 PLN/MWh / 1000 = 20 PLN
        assert ledger.export_revenue_pln[0] == 20.0
        assert ledger.sum_export_revenue_pln == 20.0

    def test_net_cost_calculation(self):
        """Verify net cost = import + fees + penalty - export."""
        grid_import_kwh = [100.0]
        grid_export_kwh = [50.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],
            export_price_pln_per_mwh=[400.0],
            other_fees_pln_per_mwh=[100.0],  # 100 PLN/MWh
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        # import: 100 * 800 / 1000 = 80 PLN
        # export: 50 * 400 / 1000 = 20 PLN
        # fees: 100 * 100 / 1000 = 10 PLN
        # net = 80 + 10 - 20 = 70 PLN
        assert abs(ledger.net_cost_pln[0] - 70.0) < 0.01
        assert abs(ledger.sum_net_cost_pln - 70.0) < 0.01

    def test_varying_prices(self):
        """Verify ledger with time-varying prices."""
        grid_import_kwh = [100.0, 100.0, 100.0]  # Same energy each step
        grid_export_kwh = [0.0, 0.0, 0.0]

        # Off-peak, peak, off-peak
        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[400.0, 1200.0, 400.0],
            export_price_pln_per_mwh=[200.0, 600.0, 200.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        # Step 0: 100 * 400 / 1000 = 40 PLN
        # Step 1: 100 * 1200 / 1000 = 120 PLN
        # Step 2: 100 * 400 / 1000 = 40 PLN
        assert ledger.import_cost_pln[0] == 40.0
        assert ledger.import_cost_pln[1] == 120.0
        assert ledger.import_cost_pln[2] == 40.0
        assert ledger.sum_import_cost_pln == 200.0

    def test_unserved_penalty(self):
        """Verify unserved load penalty calculation."""
        grid_import_kwh = [0.0]
        grid_export_kwh = [0.0]
        unserved_kwh = [10.0]  # 10 kWh unserved

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],
            export_price_pln_per_mwh=[400.0],
            unserved_penalty_pln_per_kwh=[15.0],  # 15 PLN/kWh penalty
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
            unserved_load_kwh=unserved_kwh,
        )

        # 10 kWh * 15 PLN/kWh = 150 PLN
        assert ledger.unserved_penalty_pln[0] == 150.0
        assert ledger.sum_unserved_penalty_pln == 150.0

    def test_15min_resolution(self):
        """Verify 15-minute resolution ledger."""
        n_steps = 4  # 1 hour at 15-min resolution
        grid_import_kwh = [25.0] * n_steps  # 100 kWh total
        grid_export_kwh = [0.0] * n_steps

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0] * n_steps,
            export_price_pln_per_mwh=[400.0] * n_steps,
            step_minutes=15,
            steps=n_steps,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:45:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        assert ledger.steps == 4
        assert ledger.step_minutes == 15
        # Total: 100 kWh * 800 PLN/MWh / 1000 = 80 PLN
        assert abs(ledger.sum_import_cost_pln - 80.0) < 0.01


class TestSumInvariants:
    """Tests for sum invariant validation."""

    def test_validate_sums_pass(self):
        """Verify validate_sums passes when sums match."""
        grid_import_kwh = [100.0, 100.0]
        grid_export_kwh = [50.0, 50.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0],
            step_minutes=60,
            steps=2,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T01:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        is_valid, errors = ledger.validate_sums()
        assert is_valid
        assert len(errors) == 0

    def test_validate_lengths_pass(self):
        """Verify validate_lengths passes when all arrays match."""
        grid_import_kwh = [100.0, 100.0, 100.0]
        grid_export_kwh = [50.0, 50.0, 50.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0] * 3,
            export_price_pln_per_mwh=[400.0] * 3,
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        assert ledger.validate_lengths()


class TestLedgerVsMoneyLedgerValidation:
    """Tests for ledger vs MoneyLedger reconciliation."""

    def test_validation_pass(self):
        """Verify validation passes when sums match MoneyLedger."""
        grid_import_kwh = [100.0, 100.0]  # 200 kWh
        grid_export_kwh = [50.0, 50.0]    # 100 kWh

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0],
            step_minutes=60,
            steps=2,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T01:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        # Create matching MoneyLedger
        # import: 200 * 800 / 1000 = 160 PLN
        # export: 100 * 400 / 1000 = 40 PLN
        money_ledger = MoneyLedgerTotalsPln(
            import_energy_cost_pln=160.0,
            export_revenue_pln=40.0,
            other_fees_pln=0.0,
            unserved_penalty_pln=0.0,
            total_cost_pln=120.0,  # 160 - 40
        )

        is_valid, errors = validate_ledger_vs_money_ledger(ledger, money_ledger)
        assert is_valid, f"Errors: {errors}"

    def test_validation_fail_mismatch(self):
        """Verify validation fails when sums don't match MoneyLedger."""
        grid_import_kwh = [100.0]
        grid_export_kwh = [50.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],
            export_price_pln_per_mwh=[400.0],
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        # Create mismatched MoneyLedger
        money_ledger = MoneyLedgerTotalsPln(
            import_energy_cost_pln=999.0,  # Wrong value
            export_revenue_pln=999.0,      # Wrong value
        )

        is_valid, errors = validate_ledger_vs_money_ledger(ledger, money_ledger)
        assert not is_valid
        assert len(errors) >= 2  # At least import and export mismatch


class TestEdgeCases:
    """Tests for edge cases."""

    def test_zero_energy(self):
        """Verify handling of zero energy flows."""
        grid_import_kwh = [0.0, 0.0, 0.0]
        grid_export_kwh = [0.0, 0.0, 0.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0] * 3,
            export_price_pln_per_mwh=[400.0] * 3,
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        assert ledger.sum_import_cost_pln == 0.0
        assert ledger.sum_export_revenue_pln == 0.0
        assert ledger.sum_net_cost_pln == 0.0

    def test_empty_other_fees(self):
        """Verify handling when other_fees is empty."""
        grid_import_kwh = [100.0]
        grid_export_kwh = [0.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],
            export_price_pln_per_mwh=[400.0],
            # other_fees_pln_per_mwh not set (empty)
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        assert ledger.sum_other_fees_pln == 0.0

    def test_single_step(self):
        """Verify single step ledger."""
        grid_import_kwh = [100.0]
        grid_export_kwh = [50.0]

        price_ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],
            export_price_pln_per_mwh=[400.0],
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        ledger = generate_ledger_timeseries(
            grid_import_kwh=grid_import_kwh,
            grid_export_kwh=grid_export_kwh,
            price_timeseries=price_ts,
        )

        assert ledger.steps == 1
        assert len(ledger.import_cost_pln) == 1
        assert len(ledger.net_cost_pln) == 1
