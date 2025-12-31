"""
Unit tests for invariants_helper (v1.9.0).

Tests focus on ledger reconciliation invariant and other invariant checks.
"""

import pytest
import sys
import os

# Add services/bess-dispatch to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from invariants_helper import (
    check_ledger_reconciliation,
    check_energy_balance,
    check_non_negative,
    check_cost_sums,
    check_annualization,
    compute_invariants,
    InvariantResult,
)


class TestCheckLedgerReconciliation:
    """Tests for ledger reconciliation invariant."""

    def test_passes_when_no_money_ledger(self):
        """Should pass when money_ledger is not present."""
        variant = {
            "savings_breakdown": {"net_savings_pln": 1000.0},
            # No money_ledger
        }

        result = check_ledger_reconciliation(variant)

        assert result.passed is True
        assert result.name == "ledger_reconciliation_ok"
        assert "skipped" in result.details

    def test_passes_when_values_match(self):
        """Should pass when net_savings equals ledger delta."""
        variant = {
            "savings_breakdown": {"net_savings_pln": 5000.0},
            "money_ledger": {
                "delta_annual_pln": {"total_cost_pln": 5000.0}
            }
        }

        result = check_ledger_reconciliation(variant)

        assert result.passed is True
        assert result.max_abs_error == 0.0

    def test_passes_within_tolerance(self):
        """Should pass when values differ within tolerance."""
        variant = {
            "savings_breakdown": {"net_savings_pln": 5000.0},
            "money_ledger": {
                "delta_annual_pln": {"total_cost_pln": 5000.5}  # 0.5 PLN diff
            }
        }

        result = check_ledger_reconciliation(variant, tolerance_pln=1.0)

        assert result.passed is True
        assert result.max_abs_error == 0.5

    def test_fails_when_values_differ(self):
        """Should fail when net_savings differs from ledger delta."""
        variant = {
            "savings_breakdown": {"net_savings_pln": 5000.0},
            "money_ledger": {
                "delta_annual_pln": {"total_cost_pln": 4500.0}  # 500 PLN diff
            }
        }

        result = check_ledger_reconciliation(variant, tolerance_pln=1.0)

        assert result.passed is False
        assert result.max_abs_error == 500.0
        assert "net_savings=5000.00" in result.details
        assert "ledger_delta=4500.00" in result.details

    def test_handles_missing_savings_breakdown(self):
        """Should handle missing savings_breakdown gracefully."""
        variant = {
            # No savings_breakdown
            "money_ledger": {
                "delta_annual_pln": {"total_cost_pln": 5000.0}
            }
        }

        result = check_ledger_reconciliation(variant)

        # net_savings defaults to 0, so diff = 5000
        assert result.passed is False
        assert result.max_abs_error == 5000.0

    def test_handles_negative_savings(self):
        """Should handle negative savings correctly."""
        variant = {
            "savings_breakdown": {"net_savings_pln": -1000.0},  # Negative
            "money_ledger": {
                "delta_annual_pln": {"total_cost_pln": -1000.0}
            }
        }

        result = check_ledger_reconciliation(variant)

        assert result.passed is True


class TestComputeInvariantsIncludesLedger:
    """Tests that compute_invariants includes ledger reconciliation."""

    def test_ledger_reconciliation_in_results(self):
        """compute_invariants should include ledger_reconciliation_ok."""
        variant = {
            "totals": {
                "grid_import_mwh": 10.0,
                "pv_used_mwh": 5.0,
                "battery_discharge_mwh": 2.0,
                "load_served_mwh": 12.0,
                "grid_export_mwh": 3.0,
                "battery_charge_mwh": 2.0,
            },
            "savings_breakdown": {
                "net_savings_pln": 5000.0,
                "energy_savings_pln": 5100.0,
                "degradation_cost_pln": -100.0,
            },
            "annual_savings_pln": 5000.0,
            "capex_pln": 100000.0,
            "money_ledger": {
                "delta_annual_pln": {"total_cost_pln": 5000.0}
            }
        }

        result = compute_invariants(variant)

        assert "ledger_reconciliation_ok" in result
        assert result["ledger_reconciliation_ok"] is True

    def test_all_passed_false_if_ledger_fails(self):
        """all_passed should be False if ledger reconciliation fails."""
        variant = {
            "totals": {
                "grid_import_mwh": 10.0,
                "load_served_mwh": 10.0,
            },
            "savings_breakdown": {
                "net_savings_pln": 5000.0,
                "energy_savings_pln": 5000.0,
            },
            "annual_savings_pln": 5000.0,
            "capex_pln": 100000.0,
            "money_ledger": {
                "delta_annual_pln": {"total_cost_pln": 3000.0}  # Mismatch!
            }
        }

        result = compute_invariants(variant)

        assert result["ledger_reconciliation_ok"] is False
        assert result["all_passed"] is False


class TestCheckEnergyBalance:
    """Basic tests for energy balance invariant."""

    def test_passes_when_balanced(self):
        """Should pass when energy is balanced."""
        variant = {
            "totals": {
                "grid_import_mwh": 10.0,
                "pv_used_mwh": 5.0,
                "battery_discharge_mwh": 2.0,
                "load_served_mwh": 12.0,
                "grid_export_mwh": 3.0,
                "battery_charge_mwh": 2.0,
            }
        }
        # in = 10 + 5 + 2 = 17, out = 12 + 3 + 2 = 17

        result = check_energy_balance(variant)

        assert result.passed is True

    def test_fails_when_unbalanced(self):
        """Should fail when energy is not balanced."""
        variant = {
            "totals": {
                "grid_import_mwh": 10.0,
                "load_served_mwh": 5.0,  # Significant mismatch
            }
        }

        result = check_energy_balance(variant)

        assert result.passed is False


class TestCheckNonNegative:
    """Basic tests for non-negative invariant."""

    def test_passes_with_positive_values(self):
        """Should pass when all values are non-negative."""
        variant = {
            "totals": {
                "grid_import_mwh": 10.0,
                "grid_export_mwh": 5.0,
                "battery_throughput_mwh": 20.0,
            },
            "capex_pln": 100000.0,
        }

        result = check_non_negative(variant)

        assert result.passed is True

    def test_fails_with_negative_capex(self):
        """Should fail when capex is negative."""
        variant = {
            "capex_pln": -1000.0,
        }

        result = check_non_negative(variant)

        assert result.passed is False
        assert "capex_pln" in result.details
