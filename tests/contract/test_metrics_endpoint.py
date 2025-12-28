"""
Contract test for Prometheus /metrics endpoint.
"""
import pytest
import requests


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    def test_metrics_returns_200(self, wait_for_services, bess_dispatch_url):
        """Verify /metrics endpoint returns 200 OK."""
        response = requests.get(f"{bess_dispatch_url}/metrics", timeout=10)
        assert response.status_code == 200

    def test_metrics_content_type(self, wait_for_services, bess_dispatch_url):
        """Verify /metrics returns Prometheus content type."""
        response = requests.get(f"{bess_dispatch_url}/metrics", timeout=10)
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "text/plain; charset=utf-8" in content_type

    def test_metrics_contains_process_info(self, wait_for_services, bess_dispatch_url):
        """Verify /metrics contains default Python process metrics."""
        response = requests.get(f"{bess_dispatch_url}/metrics", timeout=10)
        body = response.text
        # Default prometheus_client metrics
        assert "process_" in body or "python_" in body
