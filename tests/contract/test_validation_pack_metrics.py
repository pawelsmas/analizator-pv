"""
Contract tests for validate-pack metrics observability (v1.7.0).

Tests verify:
- Metrics are exposed via /metrics endpoint
- Pack validation records metrics correctly
- Metric labels are present and correct
"""
import pytest
import requests
import time

BASE_URL = "http://localhost:8031"


class TestValidationPackMetricsExposed:
    """Contract tests for validate-pack metrics exposure."""

    def test_metrics_endpoint_accessible(self):
        """Verify /metrics endpoint is accessible."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")

    def test_pack_requests_metric_defined(self):
        """Verify bess_validation_pack_requests_total metric is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_pack_requests_total" in response.text

    def test_pack_passed_metric_defined(self):
        """Verify bess_validation_pack_passed_total metric is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_pack_passed_total" in response.text

    def test_pack_failed_metric_defined(self):
        """Verify bess_validation_pack_failed_total metric is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_pack_failed_total" in response.text

    def test_pack_duration_metric_defined(self):
        """Verify bess_validation_pack_duration_seconds metric is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_pack_duration_seconds" in response.text

    def test_last_pack_passed_gauge_defined(self):
        """Verify bess_validation_last_pack_passed gauge is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_last_pack_passed" in response.text

    def test_last_scenarios_total_gauge_defined(self):
        """Verify bess_validation_last_scenarios_total gauge is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_last_scenarios_total" in response.text

    def test_scenario_total_metric_defined(self):
        """Verify bess_validation_scenario_total metric is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_scenario_total" in response.text

    def test_field_mismatch_count_histogram_defined(self):
        """Verify bess_validation_field_mismatch_count histogram is defined."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "bess_validation_field_mismatch_count" in response.text


class TestValidationPackMetricsRecorded:
    """Contract tests for validate-pack metrics recording."""

    @pytest.fixture(autouse=True)
    def run_validation(self):
        """Run a validation before testing metrics."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        assert response.status_code == 200
        # Give metrics time to be recorded
        time.sleep(0.5)

    def test_pack_requests_incremented(self):
        """Verify pack requests counter is incremented."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200

        # Look for the metric with baseline label
        assert 'bess_validation_pack_requests_total{pack="baseline"}' in response.text

    def test_pack_result_recorded(self):
        """Verify pack result (passed or failed) is recorded."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200

        # Either passed or failed should have baseline label
        has_passed = 'bess_validation_pack_passed_total{pack="baseline"}' in response.text
        has_failed = 'bess_validation_pack_failed_total{pack="baseline"}' in response.text
        assert has_passed or has_failed, "Pack result should be recorded"

    def test_pack_duration_recorded(self):
        """Verify pack duration is recorded in histogram."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200

        # Check histogram count is present
        assert 'bess_validation_pack_duration_seconds_count{pack="baseline"}' in response.text

    def test_last_pack_passed_gauge_set(self):
        """Verify last pack passed gauge is set."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200

        # Should have the gauge with a value (0 or 1)
        assert 'bess_validation_last_pack_passed{pack="baseline"}' in response.text

    def test_last_scenarios_total_gauge_set(self):
        """Verify last scenarios total gauge is set."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200

        # Should have the gauge with scenarios count
        lines = response.text.split("\n")
        for line in lines:
            if 'bess_validation_last_scenarios_total{pack="baseline"}' in line:
                # Extract value and verify it's > 0
                value = float(line.split()[-1])
                assert value > 0, "Should have at least one scenario"
                return
        pytest.fail("bess_validation_last_scenarios_total gauge not found")

    def test_last_scenarios_passed_gauge_set(self):
        """Verify last scenarios passed gauge is set."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200

        assert 'bess_validation_last_scenarios_passed{pack="baseline"}' in response.text

    def test_last_scenarios_failed_gauge_set(self):
        """Verify last scenarios failed gauge is set."""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200

        assert 'bess_validation_last_scenarios_failed{pack="baseline"}' in response.text
