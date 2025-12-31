"""
Contract tests for per-field validation mismatch metrics (v1.5.0).

Tests verify that the validation endpoint records:
- bess_validation_field_checked_total{scenario_id, field}
- bess_validation_field_mismatch_total{scenario_id, field}
"""

import pytest
from ._api import post_json, load_smoke_payload


# -----------------------------------------------------------------------------
# Helper: Get metrics from /metrics endpoint
# -----------------------------------------------------------------------------

def get_metrics_text() -> str:
    """Fetch raw Prometheus metrics text."""
    import requests
    resp = requests.get("http://localhost:8031/metrics")
    resp.raise_for_status()
    return resp.text


# -----------------------------------------------------------------------------
# Test: Per-Field Metrics Presence
# -----------------------------------------------------------------------------

class TestFieldMetricsPresence:
    """Test that per-field metrics appear in /metrics."""

    def test_field_checked_metric_exists_after_validation(self):
        """bess_validation_field_checked_total should appear after validation."""
        # Run a validation request
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": -68000.0},
            "scenario_id": "field_metrics_test_checked",
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        assert "bess_validation_field_checked_total" in metrics

    def test_field_mismatch_metric_exists_after_failed_validation(self):
        """bess_validation_field_mismatch_total should appear after failed validation."""
        # Run a validation that fails
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": 999999.0},  # Definitely wrong
            "scenario_id": "field_metrics_test_mismatch",
            "tolerances": {"default_rel": 0.001, "default_abs": 1.0},
        }
        result = post_json("/validate/sizing", validation_request)

        # Should fail
        assert result["passed"] == False, "Validation should fail"

        metrics = get_metrics_text()
        assert "bess_validation_field_mismatch_total" in metrics


# -----------------------------------------------------------------------------
# Test: Field Metrics Labels
# -----------------------------------------------------------------------------

class TestFieldMetricsLabels:
    """Test that per-field metrics have correct labels."""

    def test_field_checked_has_scenario_id_label(self):
        """Field checked metric should have scenario_id label."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        scenario_id = "label_test_scenario_123"
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": -68000.0},
            "scenario_id": scenario_id,
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        # Look for the scenario_id label in the metric line
        assert f'scenario_id="{scenario_id}"' in metrics

    def test_field_checked_has_field_label(self):
        """Field checked metric should have field label."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": -68000.0},
            "scenario_id": "field_label_test",
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        assert 'field="npv_pln"' in metrics


# -----------------------------------------------------------------------------
# Test: Field Metrics Counting
# -----------------------------------------------------------------------------

class TestFieldMetricsCounting:
    """Test that per-field metrics count correctly."""

    def test_multiple_fields_each_get_checked(self):
        """Each expected_kpi field should increment field_checked counter."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {
                "npv_pln": -68000.0,
                "net_savings_pln": 15.0,
            },
            "scenario_id": "multi_field_check_test",
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        # Both fields should appear in checked metrics
        assert 'field="npv_pln"' in metrics
        assert 'field="net_savings_pln"' in metrics

    def test_failed_field_appears_in_mismatch(self):
        """Field that fails tolerance should appear in mismatch metric."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {
                "npv_pln": 999999.0,  # Will fail
            },
            "scenario_id": "mismatch_field_test",
            "tolerances": {"default_rel": 0.001, "default_abs": 1.0},
        }
        result = post_json("/validate/sizing", validation_request)

        assert result["passed"] == False
        assert "npv_pln" in result["failed_fields"]

        metrics = get_metrics_text()
        # The mismatch metric should include npv_pln
        lines = [l for l in metrics.split('\n') if 'bess_validation_field_mismatch_total' in l and 'field="npv_pln"' in l]
        assert len(lines) > 0, "npv_pln should appear in mismatch metrics"


# -----------------------------------------------------------------------------
# Test: Metrics Format
# -----------------------------------------------------------------------------

class TestFieldMetricsFormat:
    """Test that metrics follow Prometheus format."""

    def test_field_checked_has_help_line(self):
        """Field checked metric should have HELP line."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": -68000.0},
            "scenario_id": "help_line_test",
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        assert "# HELP bess_validation_field_checked_total" in metrics

    def test_field_checked_has_type_line(self):
        """Field checked metric should have TYPE line."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": -68000.0},
            "scenario_id": "type_line_test",
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        assert "# TYPE bess_validation_field_checked_total counter" in metrics

    def test_field_mismatch_has_help_line(self):
        """Field mismatch metric should have HELP line."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": 999999.0},
            "scenario_id": "mismatch_help_test",
            "tolerances": {"default_rel": 0.001, "default_abs": 1.0},
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        assert "# HELP bess_validation_field_mismatch_total" in metrics

    def test_field_mismatch_has_type_line(self):
        """Field mismatch metric should have TYPE line."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        validation_request = {
            "request": payload,
            "expected_kpis": {"npv_pln": 999999.0},
            "scenario_id": "mismatch_type_test",
            "tolerances": {"default_rel": 0.001, "default_abs": 1.0},
        }
        post_json("/validate/sizing", validation_request)

        metrics = get_metrics_text()
        assert "# TYPE bess_validation_field_mismatch_total counter" in metrics
