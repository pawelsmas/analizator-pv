"""
Contract tests for MoneyLedger (v1.9.0).

Tests verify:
- MoneyLedger is present when include_money_ledger=true
- MoneyLedger has expected structure with baseline/project/delta
- MoneyLedger is NOT present when include_money_ledger=false (default)
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_sizing_request_with_money_ledger():
    """Create a sizing request with include_money_ledger=true."""
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
    }
    response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Sizing failed: {response.text}"
    return response.json()


def create_sizing_request_without_money_ledger():
    """Create a sizing request with include_money_ledger=false (default)."""
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
        # include_money_ledger defaults to false
    }
    response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Sizing failed: {response.text}"
    return response.json()


class TestMoneyLedgerPresence:
    """Contract tests for MoneyLedger presence based on flag."""

    def test_money_ledger_present_when_requested(self):
        """Verify money_ledger is present when include_money_ledger=true."""
        result = create_sizing_request_with_money_ledger()

        # Check that at least one variant has money_ledger
        variants = result.get("variants", [])
        assert len(variants) > 0, "No variants in response"

        # Check recommended variant for money_ledger
        recommended = None
        for v in variants:
            if v.get("is_recommended"):
                recommended = v
                break

        assert recommended is not None, "No recommended variant found"
        assert "money_ledger" in recommended, "money_ledger not in recommended variant"
        assert recommended["money_ledger"] is not None, "money_ledger is None"

    def test_money_ledger_not_present_by_default(self):
        """Verify money_ledger is NOT present when include_money_ledger=false."""
        result = create_sizing_request_without_money_ledger()

        variants = result.get("variants", [])
        assert len(variants) > 0, "No variants in response"

        # Check that no variant has money_ledger populated
        for v in variants:
            # money_ledger may be in response as null or not present
            money_ledger = v.get("money_ledger")
            assert money_ledger is None, f"money_ledger should be None by default, got: {money_ledger}"


class TestMoneyLedgerStructure:
    """Contract tests for MoneyLedger structure."""

    def test_baseline_period_total_cost_exists(self):
        """Verify baseline_period.total_cost_pln exists."""
        result = create_sizing_request_with_money_ledger()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        money_ledger = recommended.get("money_ledger")
        assert money_ledger is not None, "money_ledger is None"

        baseline_period = money_ledger.get("baseline_period")
        assert baseline_period is not None, "baseline_period is None"
        assert "total_cost_pln" in baseline_period, "total_cost_pln not in baseline_period"

    def test_project_period_total_cost_exists(self):
        """Verify project_period.total_cost_pln exists."""
        result = create_sizing_request_with_money_ledger()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        money_ledger = recommended.get("money_ledger")
        assert money_ledger is not None, "money_ledger is None"

        project_period = money_ledger.get("project_period")
        assert project_period is not None, "project_period is None"
        assert "total_cost_pln" in project_period, "total_cost_pln not in project_period"

    def test_delta_period_pln_exists(self):
        """Verify delta_period_pln exists with total_cost_pln."""
        result = create_sizing_request_with_money_ledger()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        money_ledger = recommended.get("money_ledger")
        assert money_ledger is not None, "money_ledger is None"

        delta_period = money_ledger.get("delta_period_pln")
        assert delta_period is not None, "delta_period_pln is None"
        assert "total_cost_pln" in delta_period, "total_cost_pln not in delta_period_pln"

    def test_annual_totals_exist(self):
        """Verify annualized totals exist."""
        result = create_sizing_request_with_money_ledger()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        money_ledger = recommended.get("money_ledger")
        assert money_ledger is not None, "money_ledger is None"

        # Check baseline_annual
        baseline_annual = money_ledger.get("baseline_annual")
        assert baseline_annual is not None, "baseline_annual is None"
        assert "total_cost_pln" in baseline_annual, "total_cost_pln not in baseline_annual"

        # Check project_annual
        project_annual = money_ledger.get("project_annual")
        assert project_annual is not None, "project_annual is None"
        assert "total_cost_pln" in project_annual, "total_cost_pln not in project_annual"

        # Check delta_annual_pln
        delta_annual = money_ledger.get("delta_annual_pln")
        assert delta_annual is not None, "delta_annual_pln is None"
        assert "total_cost_pln" in delta_annual, "total_cost_pln not in delta_annual_pln"

    def test_period_hours_exists(self):
        """Verify period_hours field exists."""
        result = create_sizing_request_with_money_ledger()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        money_ledger = recommended.get("money_ledger")
        assert money_ledger is not None, "money_ledger is None"

        assert "period_hours" in money_ledger, "period_hours not in money_ledger"
        assert isinstance(money_ledger["period_hours"], int), "period_hours should be int"


class TestMoneyLedgerCostCategories:
    """Contract tests for MoneyLedger cost category fields."""

    def test_baseline_period_has_all_cost_categories(self):
        """Verify baseline_period has all cost category fields."""
        result = create_sizing_request_with_money_ledger()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        money_ledger = recommended.get("money_ledger")
        baseline_period = money_ledger.get("baseline_period")

        expected_fields = [
            "import_energy_cost_pln",
            "export_revenue_pln",
            "other_fees_pln",
            "capacity_fee_pln",
            "demand_charge_pln",
            "unserved_penalty_pln",
            "degradation_cost_pln",
            "total_cost_pln",
        ]

        for field in expected_fields:
            assert field in baseline_period, f"{field} not in baseline_period"

    def test_project_period_has_all_cost_categories(self):
        """Verify project_period has all cost category fields."""
        result = create_sizing_request_with_money_ledger()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        money_ledger = recommended.get("money_ledger")
        project_period = money_ledger.get("project_period")

        expected_fields = [
            "import_energy_cost_pln",
            "export_revenue_pln",
            "other_fees_pln",
            "capacity_fee_pln",
            "demand_charge_pln",
            "unserved_penalty_pln",
            "degradation_cost_pln",
            "total_cost_pln",
        ]

        for field in expected_fields:
            assert field in project_period, f"{field} not in project_period"
