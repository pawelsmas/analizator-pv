"""
Contract tests for LedgerTimeseries output (v2.0.0 PR3).

Tests verify:
- Without flag: ledger_timeseries absent
- With flag: ledger_timeseries present with correct structure
- Sum invariants match array sums
- Per-step costs sum to MoneyLedger totals (within tolerance)
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_sizing_request(n_hours: int = 24, include_ledger_timeseries: bool = False, include_money_ledger: bool = False):
    """Create a basic sizing request."""
    return {
        "pv_generation_kw": [50.0] * n_hours,
        "load_kw": [30.0] * n_hours,
        "interval_minutes": 60,
        "battery_power_kw": 50.0,
        "battery_energy_kwh": 100.0,
        "mode": "pv_surplus",
        "prices": {
            "import_price_pln_mwh": 800.0,
            "export_price_pln_mwh": 400.0,
        },
        "include_ledger_timeseries": include_ledger_timeseries,
        "include_money_ledger": include_money_ledger,
    }


class TestLedgerTimeseriesOutput:
    """Contract tests for ledger_timeseries output."""

    def test_ledger_timeseries_absent_without_flag(self):
        """Verify ledger_timeseries is absent when flag is false."""
        request = create_sizing_request(include_ledger_timeseries=False)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        variants = result.get("variants", [])
        assert len(variants) > 0, "No variants in response"

        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        assert "ledger_timeseries" not in recommended or recommended.get("ledger_timeseries") is None, \
            "ledger_timeseries should be absent without flag"

    def test_ledger_timeseries_present_with_flag(self):
        """Verify ledger_timeseries is present when flag is true."""
        request = create_sizing_request(include_ledger_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        ledger_ts = recommended.get("ledger_timeseries")
        assert ledger_ts is not None, "ledger_timeseries should be present with flag"

        # Verify structure
        assert "import_cost_pln" in ledger_ts
        assert "export_revenue_pln" in ledger_ts
        assert "net_cost_pln" in ledger_ts
        assert "steps" in ledger_ts
        assert "step_minutes" in ledger_ts

    def test_ledger_timeseries_length_matches_steps(self):
        """Verify cost array length matches steps."""
        n_hours = 48
        request = create_sizing_request(n_hours=n_hours, include_ledger_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        ledger_ts = recommended.get("ledger_timeseries")

        assert ledger_ts is not None
        assert len(ledger_ts["import_cost_pln"]) == n_hours, \
            f"Expected {n_hours} import costs, got {len(ledger_ts['import_cost_pln'])}"
        assert len(ledger_ts["export_revenue_pln"]) == n_hours, \
            f"Expected {n_hours} export revenues, got {len(ledger_ts['export_revenue_pln'])}"
        assert len(ledger_ts["net_cost_pln"]) == n_hours, \
            f"Expected {n_hours} net costs, got {len(ledger_ts['net_cost_pln'])}"
        assert ledger_ts["steps"] == n_hours

    def test_sum_invariants_present(self):
        """Verify sum fields are present in ledger_timeseries."""
        request = create_sizing_request(include_ledger_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        ledger_ts = recommended.get("ledger_timeseries")

        assert "sum_import_cost_pln" in ledger_ts
        assert "sum_export_revenue_pln" in ledger_ts
        assert "sum_net_cost_pln" in ledger_ts

    def test_sum_invariants_match_arrays(self):
        """Verify sum fields match actual array sums."""
        request = create_sizing_request(include_ledger_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        ledger_ts = recommended.get("ledger_timeseries")

        # Check import cost sum
        actual_import_sum = sum(ledger_ts["import_cost_pln"])
        assert abs(actual_import_sum - ledger_ts["sum_import_cost_pln"]) < 0.01, \
            f"Import sum mismatch: {actual_import_sum} != {ledger_ts['sum_import_cost_pln']}"

        # Check export revenue sum
        actual_export_sum = sum(ledger_ts["export_revenue_pln"])
        assert abs(actual_export_sum - ledger_ts["sum_export_revenue_pln"]) < 0.01, \
            f"Export sum mismatch: {actual_export_sum} != {ledger_ts['sum_export_revenue_pln']}"

        # Check net cost sum
        actual_net_sum = sum(ledger_ts["net_cost_pln"])
        assert abs(actual_net_sum - ledger_ts["sum_net_cost_pln"]) < 0.01, \
            f"Net sum mismatch: {actual_net_sum} != {ledger_ts['sum_net_cost_pln']}"

    def test_ledger_vs_money_ledger_reconciliation(self):
        """Verify ledger_timeseries sums approximate MoneyLedger totals."""
        request = create_sizing_request(
            include_ledger_timeseries=True,
            include_money_ledger=True,
        )
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        ledger_ts = recommended.get("ledger_timeseries")
        money_ledger = recommended.get("money_ledger")

        if money_ledger is None:
            pytest.skip("money_ledger not present in response")

        # Compare ledger_timeseries sums with money_ledger.project_period
        project = money_ledger.get("project_period", {})

        # Tolerance: 1% or 10 PLN, whichever is larger
        import_ledger = ledger_ts["sum_import_cost_pln"]
        import_money = project.get("import_energy_cost_pln", 0)
        tolerance = max(abs(import_money) * 0.01, 10.0)

        assert abs(import_ledger - import_money) < tolerance, \
            f"Import mismatch: ledger={import_ledger:.2f} != money_ledger={import_money:.2f}"

    def test_15min_resolution(self):
        """Verify 15-minute resolution ledger."""
        n_hours = 24
        n_steps_15min = n_hours * 4

        request = {
            "pv_generation_kw": [50.0] * n_steps_15min,
            "load_kw": [30.0] * n_steps_15min,
            "interval_minutes": 15,
            "battery_power_kw": 50.0,
            "battery_energy_kwh": 100.0,
            "mode": "pv_surplus",
            "prices": {
                "import_price_pln_mwh": 800.0,
                "export_price_pln_mwh": 400.0,
            },
            "include_ledger_timeseries": True,
        }

        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        assert response.status_code == 200, f"Sizing failed: {response.text}"

        result = response.json()
        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        ledger_ts = recommended.get("ledger_timeseries")

        assert ledger_ts["step_minutes"] == 15
        assert ledger_ts["steps"] == n_steps_15min
        assert len(ledger_ts["import_cost_pln"]) == n_steps_15min

    def test_costs_are_plausible(self):
        """Verify cost values are plausible (not negative, not huge)."""
        request = create_sizing_request(include_ledger_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        ledger_ts = recommended.get("ledger_timeseries")

        # Import costs should be >= 0
        for cost in ledger_ts["import_cost_pln"]:
            assert cost >= 0, f"Negative import cost: {cost}"

        # Export revenue should be >= 0
        for revenue in ledger_ts["export_revenue_pln"]:
            assert revenue >= 0, f"Negative export revenue: {revenue}"

    def test_ledger_deterministic(self):
        """Verify same request produces same ledger_timeseries."""
        request = create_sizing_request(include_ledger_timeseries=True)

        response1 = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        response2 = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response1.status_code == 200
        assert response2.status_code == 200

        result1 = response1.json()
        result2 = response2.json()

        recommended1 = next((v for v in result1.get("variants", []) if v.get("is_recommended")), None)
        recommended2 = next((v for v in result2.get("variants", []) if v.get("is_recommended")), None)

        ledger1 = recommended1.get("ledger_timeseries")
        ledger2 = recommended2.get("ledger_timeseries")

        assert ledger1["sum_import_cost_pln"] == ledger2["sum_import_cost_pln"], \
            "Ledger should be deterministic"
        assert ledger1["sum_export_revenue_pln"] == ledger2["sum_export_revenue_pln"], \
            "Ledger should be deterministic"
