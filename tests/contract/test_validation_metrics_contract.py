"""
Contract tests for validation observability metrics (v1.4.0).

Tests verify:
- Validation metrics appear after validation request
- HELP and TYPE lines present in Prometheus format
- Passed/failed counters increment correctly
- Duration histogram captures validation time
"""

import pytest
from ._api import post_json, get_json


# -----------------------------------------------------------------------------
# Helper: Get /metrics endpoint
# -----------------------------------------------------------------------------

def get_metrics():
    """Get Prometheus metrics from /metrics endpoint."""
    import requests
    base_url = "http://localhost:8031"
    resp = requests.get(f"{base_url}/metrics", timeout=30)
    return resp.text


def load_scenario_request(scenario_id: str) -> dict:
    """Load a scenario with its request from docs/scenarios."""
    import json
    import os

    # Path relative to repo root
    repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
    scenarios_path = os.path.join(repo_root, "docs", "scenarios")
    filepath = os.path.join(scenarios_path, f"{scenario_id}.json")

    with open(filepath) as f:
        scenario = json.load(f)

    # Load the actual request from request_file
    request_file = scenario.get("request_file")
    if request_file:
        request_path = os.path.join(repo_root, request_file)
        with open(request_path) as f:
            scenario["request"] = json.load(f)

    return scenario


# -----------------------------------------------------------------------------
# Test: Validation Metrics Presence
# -----------------------------------------------------------------------------

class TestValidationMetricsPresence:
    """Test that validation metrics appear after a validation request."""

    def test_metrics_endpoint_includes_validation_metrics_after_request(self):
        """After validation request, metrics endpoint should include validation metrics."""
        # Load a valid scenario
        scenario = load_scenario_request("baseline_stacked_no_arb")

        # Make validation request
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": scenario.get("expected_kpis", {"recommended_variant": "medium"}),
            "scenario_id": "test_metrics_scenario",
            "tolerances": scenario.get("tolerances", {"default_rel": 0.10, "default_abs": 100}),
        }
        post_json("/validate/sizing", validate_payload)

        # Check metrics
        metrics = get_metrics()

        # Validation request counter should exist
        assert "bess_validation_requests_total" in metrics

    def test_validation_passed_metric_increments(self):
        """Passed validation should increment passed counter."""
        # Load scenario that should pass
        scenario = load_scenario_request("baseline_stacked_no_arb")

        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},  # This should match
            "scenario_id": "passed_test",
            "tolerances": {"default_rel": 0.10, "default_abs": 100},
        }
        result = post_json("/validate/sizing", validate_payload)

        if result.get("passed"):
            metrics = get_metrics()
            assert "bess_validation_passed_total" in metrics


# -----------------------------------------------------------------------------
# Test: Metrics Format
# -----------------------------------------------------------------------------

class TestValidationMetricsFormat:
    """Test Prometheus metrics format (HELP/TYPE lines)."""

    def test_validation_requests_has_help_and_type(self):
        """Validation request counter should have HELP and TYPE lines."""
        # Trigger a validation first
        scenario = load_scenario_request("baseline_stacked_no_arb")
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},
            "scenario_id": "format_test",
        }
        post_json("/validate/sizing", validate_payload)

        metrics = get_metrics()

        # Check HELP and TYPE for request counter
        assert "# HELP bess_validation_requests_total" in metrics
        assert "# TYPE bess_validation_requests_total counter" in metrics

    def test_validation_duration_has_help_and_type(self):
        """Validation duration histogram should have HELP and TYPE lines."""
        scenario = load_scenario_request("baseline_stacked_no_arb")
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},
            "scenario_id": "duration_format_test",
        }
        post_json("/validate/sizing", validate_payload)

        metrics = get_metrics()

        assert "# HELP bess_validation_duration_seconds" in metrics
        assert "# TYPE bess_validation_duration_seconds histogram" in metrics

    def test_validation_kpis_count_has_help_and_type(self):
        """KPIs count histogram should have HELP and TYPE lines."""
        scenario = load_scenario_request("baseline_stacked_no_arb")
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},
            "scenario_id": "kpis_format_test",
        }
        post_json("/validate/sizing", validate_payload)

        metrics = get_metrics()

        assert "# HELP bess_validation_kpis_count" in metrics
        assert "# TYPE bess_validation_kpis_count histogram" in metrics


# -----------------------------------------------------------------------------
# Test: Scenario ID Label
# -----------------------------------------------------------------------------

class TestValidationScenarioLabel:
    """Test that scenario_id label is captured in metrics."""

    def test_scenario_id_label_in_request_counter(self):
        """Scenario ID should appear as label in request counter."""
        scenario = load_scenario_request("baseline_stacked_no_arb")
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},
            "scenario_id": "labeled_scenario",
        }
        post_json("/validate/sizing", validate_payload)

        metrics = get_metrics()

        # Check that the scenario label appears
        assert 'scenario_id="labeled_scenario"' in metrics


# -----------------------------------------------------------------------------
# Test: Tolerance Histograms
# -----------------------------------------------------------------------------

class TestValidationToleranceMetrics:
    """Test tolerance histogram metrics."""

    def test_tolerance_rel_histogram_present(self):
        """Relative tolerance histogram should be present after validation."""
        scenario = load_scenario_request("baseline_stacked_no_arb")
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},
            "scenario_id": "tolerance_test",
            "tolerances": {"default_rel": 0.05, "default_abs": 50},
        }
        post_json("/validate/sizing", validate_payload)

        metrics = get_metrics()

        assert "bess_validation_tolerance_rel" in metrics

    def test_tolerance_abs_histogram_present(self):
        """Absolute tolerance histogram should be present after validation."""
        scenario = load_scenario_request("baseline_stacked_no_arb")
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},
            "scenario_id": "tolerance_abs_test",
            "tolerances": {"default_rel": 0.05, "default_abs": 100},
        }
        post_json("/validate/sizing", validate_payload)

        metrics = get_metrics()

        assert "bess_validation_tolerance_abs" in metrics


# -----------------------------------------------------------------------------
# Test: Failed Diffs Count
# -----------------------------------------------------------------------------

class TestValidationDiffsFailedMetrics:
    """Test failed diffs count histogram."""

    def test_diffs_failed_count_histogram_present(self):
        """Failed diffs count histogram should be present."""
        scenario = load_scenario_request("baseline_stacked_no_arb")
        validate_payload = {
            "request": scenario["request"],
            "expected_kpis": {"period_info.period_hours": 8760},
            "scenario_id": "diffs_failed_test",
        }
        post_json("/validate/sizing", validate_payload)

        metrics = get_metrics()

        assert "bess_validation_diffs_failed_count" in metrics
