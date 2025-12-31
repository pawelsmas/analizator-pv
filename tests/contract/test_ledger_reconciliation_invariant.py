"""
Contract tests for ledger reconciliation invariant (v1.9.0).

Tests verify:
- When both include_invariants and include_money_ledger are true,
  ledger_reconciliation_ok is present in invariants
- ledger_reconciliation_ok passes for valid sizing results
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_sizing_request_with_ledger_and_invariants():
    """Create a sizing request with both money_ledger and invariants enabled."""
    n_hours = 24
    request = {
        "pv_generation_kw": [50.0] * n_hours,
        "load_kw": [30.0] * n_hours,
        "interval_minutes": 60,
        "battery_power_kw": 50.0,
        "battery_energy_kwh": 100.0,
        "mode": "pv_surplus",
        "prices": {
            "import_price_pln_kwh": 0.8,
            "export_price_pln_kwh": 0.4,
        },
        "include_money_ledger": True,
        "include_invariants": True,
    }
    response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Sizing failed: {response.text}"
    return response.json()


class TestLedgerReconciliationInvariant:
    """Contract tests for ledger reconciliation invariant."""

    def test_ledger_reconciliation_ok_present_in_invariants(self):
        """Verify ledger_reconciliation_ok is present when both flags enabled."""
        result = create_sizing_request_with_ledger_and_invariants()

        variants = result.get("variants", [])
        assert len(variants) > 0, "No variants in response"

        # Check recommended variant
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        invariants = recommended.get("invariants")
        assert invariants is not None, "invariants should be present"
        assert "ledger_reconciliation_ok" in invariants, \
            "ledger_reconciliation_ok should be in invariants"

    def test_ledger_reconciliation_passes_for_valid_result(self):
        """Verify ledger_reconciliation_ok is True for valid sizing."""
        result = create_sizing_request_with_ledger_and_invariants()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        invariants = recommended.get("invariants", {})

        assert invariants.get("ledger_reconciliation_ok") is True, \
            f"Expected ledger_reconciliation_ok=True, got invariants: {invariants}"

    def test_all_passed_true_with_ledger(self):
        """Verify all_passed is True when ledger reconciliation passes."""
        result = create_sizing_request_with_ledger_and_invariants()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        invariants = recommended.get("invariants", {})

        assert invariants.get("all_passed") is True, \
            f"Expected all_passed=True, got invariants: {invariants}"

    def test_net_savings_equals_ledger_delta(self):
        """Verify net_savings_pln equals delta_annual_pln.total_cost_pln."""
        result = create_sizing_request_with_ledger_and_invariants()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)

        savings_breakdown = recommended.get("dispatch_summary", {}).get("savings_breakdown", {})
        net_savings = savings_breakdown.get("net_savings_pln", 0)

        money_ledger = recommended.get("money_ledger", {})
        delta_annual = money_ledger.get("delta_annual_pln", {})
        ledger_delta = delta_annual.get("total_cost_pln", 0)

        # They should match within 1 PLN tolerance
        assert abs(net_savings - ledger_delta) < 1.0, \
            f"Reconciliation mismatch: net_savings={net_savings:.2f}, ledger_delta={ledger_delta:.2f}"
