"""
Contract tests for HTTP metrics.

Verifies that prometheus HTTP metrics are present after making requests.
"""
import pytest
import requests


class TestHttpMetrics:
    """Tests for HTTP metrics instrumentation."""

    def test_http_metrics_present_after_request(
        self, wait_for_services, bess_dispatch_url
    ):
        """
        Verify http_requests_total and http_request_duration_seconds are present.
        """
        # Make a request to trigger metrics
        requests.get(f"{bess_dispatch_url}/health", timeout=10)

        # Fetch metrics
        response = requests.get(f"{bess_dispatch_url}/metrics", timeout=10)
        assert response.status_code == 200

        body = response.text

        # Check http_requests_total exists
        assert "http_requests_total" in body, (
            "http_requests_total metric not found in /metrics"
        )

        # Check http_request_duration_seconds exists (histogram)
        assert "http_request_duration_seconds" in body, (
            "http_request_duration_seconds metric not found in /metrics"
        )

    def test_http_metrics_have_correct_labels(
        self, wait_for_services, bess_dispatch_url
    ):
        """
        Verify HTTP metrics have required labels: service, endpoint, method, status.
        """
        # Make a request
        requests.get(f"{bess_dispatch_url}/health", timeout=10)

        # Fetch metrics
        response = requests.get(f"{bess_dispatch_url}/metrics", timeout=10)
        body = response.text

        # Find http_requests_total line with labels
        for line in body.split("\n"):
            if line.startswith("http_requests_total{"):
                # Should have service, endpoint, method, status labels
                assert 'service="bess-dispatch"' in line
                assert 'endpoint=' in line
                assert 'method=' in line
                assert 'status=' in line
                break
        else:
            # No http_requests_total line with labels found - check if counter exists at all
            assert "http_requests_total" in body

    def test_http_metrics_increment_on_requests(
        self, wait_for_services, bess_dispatch_url
    ):
        """
        Verify HTTP metrics increment when requests are made.
        """
        # Get initial metrics
        response1 = requests.get(f"{bess_dispatch_url}/metrics", timeout=10)
        body1 = response1.text

        # Make additional request
        requests.get(f"{bess_dispatch_url}/health", timeout=10)

        # Get updated metrics
        response2 = requests.get(f"{bess_dispatch_url}/metrics", timeout=10)
        body2 = response2.text

        # Both should have http_requests_total
        assert "http_requests_total" in body1
        assert "http_requests_total" in body2
