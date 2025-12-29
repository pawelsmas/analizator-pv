"""
Contract tests for v0.9.0 batch sizing observability metrics.

Tests verify:
- Batch metrics appear in /metrics after batch request
- Portfolio metrics appear when portfolio_summary present
- Prometheus format is correct

Run with: pytest tests/contract/test_batch_metrics_contract.py -v
"""
import pytest
import requests
from ._api import post_json


BASE_URL = "http://localhost:8031"
BATCH_ENDPOINT = "/sizing:batch"
METRICS_ENDPOINT = "/metrics"


# Minimal batch request for testing
def make_batch_request(num_items: int = 2):
    """Create batch request with specified number of items."""
    items = []
    for i in range(num_items):
        items.append({
            "item_id": f"item_{i}",
            "request": {
                "load_kw": [100 + i * 10, 120 + i * 10, 110 + i * 10, 90 + i * 10],
                "pv_generation_kw": [50, 70, 80, 60],
                "energy_price_pln_kwh": 0.8,
            }
        })
    return {"items": items}


def get_metrics() -> str:
    """Fetch metrics endpoint content."""
    resp = requests.get(f"{BASE_URL}{METRICS_ENDPOINT}")
    resp.raise_for_status()
    return resp.text


class TestBatchMetricsPresence:
    """Tests for batch metrics presence in /metrics."""

    def test_batch_requests_counter_after_batch_call(self):
        """Verify bess_batch_sizing_requests_total counter exists after batch call."""
        # Make a batch request first
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        # Check metrics
        metrics = get_metrics()
        assert "bess_batch_sizing_requests_total" in metrics

    def test_batch_items_count_histogram_exists(self):
        """Verify bess_batch_items_count histogram exists."""
        req = make_batch_request(3)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "bess_batch_items_count" in metrics

    def test_batch_ok_count_histogram_exists(self):
        """Verify bess_batch_ok_count histogram exists."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "bess_batch_ok_count" in metrics

    def test_batch_processing_time_histogram_exists(self):
        """Verify bess_batch_processing_time_ms histogram exists."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "bess_batch_processing_time_ms" in metrics


class TestPortfolioMetricsPresence:
    """Tests for portfolio summary metrics presence."""

    def test_portfolio_summary_requests_counter_exists(self):
        """Verify bess_portfolio_summary_requests_total counter exists."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "bess_portfolio_summary_requests_total" in metrics

    def test_portfolio_optimal_variant_counter_exists(self):
        """Verify bess_portfolio_optimal_variant_total counter exists."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "bess_portfolio_optimal_variant_total" in metrics

    def test_portfolio_total_npv_histogram_exists(self):
        """Verify bess_portfolio_total_npv_kpln histogram exists."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "bess_portfolio_total_npv_kpln" in metrics

    def test_portfolio_avg_payback_histogram_exists(self):
        """Verify bess_portfolio_avg_payback_years histogram exists."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "bess_portfolio_avg_payback_years" in metrics


class TestMetricsFormat:
    """Tests for Prometheus metrics format."""

    def test_metrics_have_help_lines(self):
        """Verify metrics have HELP lines."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "# HELP bess_batch_sizing_requests_total" in metrics
        assert "# HELP bess_portfolio_summary_requests_total" in metrics

    def test_metrics_have_type_lines(self):
        """Verify metrics have TYPE lines."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        assert "# TYPE bess_batch_sizing_requests_total counter" in metrics
        assert "# TYPE bess_batch_items_count histogram" in metrics

    def test_histogram_has_bucket_lines(self):
        """Verify histograms have bucket lines."""
        req = make_batch_request(2)
        post_json(BATCH_ENDPOINT, req)

        metrics = get_metrics()
        # Histograms should have _bucket suffix
        assert "bess_batch_items_count_bucket" in metrics
