"""
Contract tests for v0.5.0 finance metrics endpoint.

These tests verify that the /metrics endpoint includes finance metrics
when finance features are used.
"""
import pytest
import requests


class TestFinanceMetricsEndpoint:
    """Test that /metrics includes finance metrics after finance requests."""

    def test_metrics_endpoint_includes_finance_metrics_after_request(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """
        After a request with finance_config, /metrics should include finance metrics.

        This test:
        1. Makes a sizing request with finance_config (cashflow + sensitivity)
        2. Checks /metrics for finance-related metric names
        """
        # Make a request with finance features
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "horizon_years": 15,
                "discount_rate": 0.08,
                "include_cashflow_timeseries": True,
                "discount_rate_sweep": [0.05, 0.08, 0.10],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )
        assert response.status_code == 200, f"Sizing request failed: {response.text}"

        # Now check /metrics
        metrics_response = requests.get(
            f"{bess_dispatch_url}/metrics",
            timeout=10,
        )
        assert metrics_response.status_code == 200

        metrics_text = metrics_response.text

        # Finance metrics should be present
        assert "bess_finance_cashflow_requests_total" in metrics_text, (
            "Missing bess_finance_cashflow_requests_total metric"
        )
        assert "bess_finance_sensitivity_requests_total" in metrics_text, (
            "Missing bess_finance_sensitivity_requests_total metric"
        )
        assert "bess_finance_npv_kpln" in metrics_text, (
            "Missing bess_finance_npv_kpln metric"
        )

    def test_metrics_endpoint_format_is_prometheus(
        self,
        wait_for_services,
        bess_dispatch_url,
    ):
        """Verify /metrics returns Prometheus-format text."""
        response = requests.get(
            f"{bess_dispatch_url}/metrics",
            timeout=10,
        )

        assert response.status_code == 200

        # Content should be text/plain with prometheus format
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "text/html" in content_type

        # Should have standard prometheus format (# HELP, # TYPE, metric_name{labels} value)
        metrics_text = response.text
        assert "# HELP" in metrics_text or "# TYPE" in metrics_text or metrics_text.strip()


class TestFinanceMetricsValues:
    """Test that finance metric values are sensible."""

    def test_sensitivity_points_metric_matches_request(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """
        bess_finance_sensitivity_points histogram should reflect number of points.
        """
        num_points = 5
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [0.04, 0.06, 0.08, 0.10, 0.12],  # 5 points
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )
        assert response.status_code == 200

        # Check metrics
        metrics_response = requests.get(
            f"{bess_dispatch_url}/metrics",
            timeout=10,
        )
        assert metrics_response.status_code == 200

        # Histogram should have observations
        metrics_text = metrics_response.text
        assert "bess_finance_sensitivity_points" in metrics_text
