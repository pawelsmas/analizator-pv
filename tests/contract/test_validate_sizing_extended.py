"""
Contract tests for /validate/sizing top_mismatches and debug_summary (v1.8.0).

Tests verify:
- top_mismatches is present in response
- top_mismatches is sorted by abs_diff descending
- top_mismatches has correct structure
- debug_summary is present in response
- debug_summary has correct structure
"""
import pytest
import requests

BASE_URL = "http://localhost:8031"


def get_validation_result_with_mismatches():
    """
    Run validation with expected KPIs that will cause mismatches.

    We intentionally set wrong expected values to get mismatches.
    """
    n_hours = 24
    request = {
        "request": {
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
        },
        "expected_kpis": {
            # Intentionally wrong values to trigger mismatches
            "npv_pln": 999999.0,
            "payback_years": 1.0,
            "annual_savings_pln": 50000.0,
            "total_pv_mwh": 999.0,
            "total_load_mwh": 888.0,
        },
        "tolerances": {
            "default_abs": 0.1,
            "default_rel": 0.001,
        },
        "scenario_id": "test_mismatches",
    }
    response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Validation failed: {response.text}"
    return response.json()


def get_validation_result_passing():
    """
    Run validation that passes (to test debug_summary with passing validation).

    We use very relaxed tolerances to ensure it passes.
    """
    n_hours = 24
    sizing_request = {
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
    }

    # Use expected values that are close to reality with very relaxed tolerances
    # total_pv_mwh = 50 * 24 / 1000 = 1.2 MWh
    # total_load_mwh = 30 * 24 / 1000 = 0.72 MWh
    request = {
        "request": sizing_request,
        "expected_kpis": {
            "total_pv_mwh": 1.2,
            "total_load_mwh": 0.72,
        },
        "tolerances": {
            "default_abs": 10.0,  # Very relaxed absolute tolerance
            "default_rel": 0.5,   # 50% relative tolerance
        },
        "scenario_id": "test_passing",
    }
    response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Validation failed: {response.text}"
    return response.json()


class TestTopMismatchesPresent:
    """Contract tests for top_mismatches presence and structure."""

    def test_top_mismatches_in_response(self):
        """Verify top_mismatches is present in response."""
        result = get_validation_result_with_mismatches()
        assert "top_mismatches" in result
        assert isinstance(result["top_mismatches"], list)

    def test_top_mismatches_not_empty_when_fails(self):
        """Verify top_mismatches is not empty when validation fails."""
        result = get_validation_result_with_mismatches()
        assert result["passed"] is False
        assert len(result["top_mismatches"]) > 0

    def test_top_mismatches_max_5_items(self):
        """Verify top_mismatches has at most 5 items."""
        result = get_validation_result_with_mismatches()
        assert len(result["top_mismatches"]) <= 5

    def test_top_mismatches_has_required_fields(self):
        """Verify each top mismatch has required fields."""
        result = get_validation_result_with_mismatches()
        for mismatch in result["top_mismatches"]:
            assert "field" in mismatch
            assert "expected" in mismatch
            assert "actual" in mismatch
            assert "abs_diff" in mismatch
            # rel_diff_pct is optional (None when expected is 0)
            assert "rel_diff_pct" in mismatch

    def test_top_mismatches_sorted_by_abs_diff_descending(self):
        """Verify top_mismatches is sorted by abs_diff descending."""
        result = get_validation_result_with_mismatches()
        mismatches = result["top_mismatches"]
        if len(mismatches) > 1:
            for i in range(len(mismatches) - 1):
                assert mismatches[i]["abs_diff"] >= mismatches[i + 1]["abs_diff"], (
                    f"Mismatches not sorted: {mismatches[i]['abs_diff']} < {mismatches[i + 1]['abs_diff']}"
                )

    def test_top_mismatches_empty_when_passes(self):
        """Verify top_mismatches is empty when validation passes."""
        result = get_validation_result_passing()
        assert result["passed"] is True
        assert len(result["top_mismatches"]) == 0


class TestDebugSummaryPresent:
    """Contract tests for debug_summary presence and structure."""

    def test_debug_summary_in_response(self):
        """Verify debug_summary is present in response."""
        result = get_validation_result_with_mismatches()
        assert "debug_summary" in result

    def test_debug_summary_not_null(self):
        """Verify debug_summary is not null."""
        result = get_validation_result_with_mismatches()
        assert result["debug_summary"] is not None

    def test_debug_summary_has_steps(self):
        """Verify debug_summary has steps field."""
        result = get_validation_result_with_mismatches()
        debug_summary = result["debug_summary"]
        assert "steps" in debug_summary
        assert debug_summary["steps"] == 24  # 24 hours

    def test_debug_summary_has_export_limited_fields(self):
        """Verify debug_summary has export_limited fields."""
        result = get_validation_result_with_mismatches()
        debug_summary = result["debug_summary"]
        assert "export_limited_steps" in debug_summary
        assert "export_limited_mwh" in debug_summary

    def test_debug_summary_has_import_limited_fields(self):
        """Verify debug_summary has import_limited fields."""
        result = get_validation_result_with_mismatches()
        debug_summary = result["debug_summary"]
        assert "import_limited_steps" in debug_summary
        assert "import_limited_mwh" in debug_summary

    def test_debug_summary_has_pv_curtail_fields(self):
        """Verify debug_summary has pv_curtail fields."""
        result = get_validation_result_with_mismatches()
        debug_summary = result["debug_summary"]
        assert "pv_curtail_steps" in debug_summary
        assert "pv_curtail_mwh" in debug_summary

    def test_debug_summary_has_unserved_load_fields(self):
        """Verify debug_summary has unserved_load fields."""
        result = get_validation_result_with_mismatches()
        debug_summary = result["debug_summary"]
        assert "unserved_load_steps" in debug_summary
        assert "unserved_load_kwh" in debug_summary

    def test_debug_summary_in_passing_validation(self):
        """Verify debug_summary is present even when validation passes."""
        result = get_validation_result_passing()
        assert result["passed"] is True
        assert "debug_summary" in result
        assert result["debug_summary"] is not None
