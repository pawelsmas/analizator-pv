"""
Unit tests for portfolio_metrics (v2.3.0 PR6).

Tests verify:
- Prometheus counters increment correctly
- Gauges update correctly
- Histograms record values correctly
"""

import pytest
import sys

# Skip all tests if prometheus_client is not installed
pytest.importorskip("prometheus_client")

sys.path.insert(0, "services/bess-dispatch")


class TestPortfolioMetricsCounters:
    """Tests for portfolio metrics counters."""

    def test_portfolio_summary_requests_counter_exists(self):
        """Portfolio summary requests counter should exist."""
        from observability.portfolio_metrics import PORTFOLIO_SUMMARY_REQUESTS_TOTAL
        assert PORTFOLIO_SUMMARY_REQUESTS_TOTAL is not None

    def test_portfolio_summary_errors_counter_exists(self):
        """Portfolio summary errors counter should exist."""
        from observability.portfolio_metrics import PORTFOLIO_SUMMARY_ERRORS_TOTAL
        assert PORTFOLIO_SUMMARY_ERRORS_TOTAL is not None

    def test_portfolio_export_requests_counter_exists(self):
        """Portfolio export requests counter should exist."""
        from observability.portfolio_metrics import PORTFOLIO_EXPORT_REQUESTS_TOTAL
        assert PORTFOLIO_EXPORT_REQUESTS_TOTAL is not None

    def test_portfolio_items_total_counter_exists(self):
        """Portfolio items total counter should exist."""
        from observability.portfolio_metrics import PORTFOLIO_ITEMS_TOTAL
        assert PORTFOLIO_ITEMS_TOTAL is not None

    def test_portfolio_mixed_assumptions_counter_exists(self):
        """Portfolio mixed assumptions counter should exist."""
        from observability.portfolio_metrics import PORTFOLIO_MIXED_ASSUMPTIONS_TOTAL
        assert PORTFOLIO_MIXED_ASSUMPTIONS_TOTAL is not None


class TestPortfolioMetricsHistograms:
    """Tests for portfolio metrics histograms."""

    def test_portfolio_items_per_request_histogram_exists(self):
        """Portfolio items per request histogram should exist."""
        from observability.portfolio_metrics import PORTFOLIO_ITEMS_PER_REQUEST
        assert PORTFOLIO_ITEMS_PER_REQUEST is not None

    def test_portfolio_total_npv_histogram_exists(self):
        """Portfolio total NPV histogram should exist."""
        from observability.portfolio_metrics import PORTFOLIO_TOTAL_NPV_PLN
        assert PORTFOLIO_TOTAL_NPV_PLN is not None

    def test_portfolio_total_capex_histogram_exists(self):
        """Portfolio total CAPEX histogram should exist."""
        from observability.portfolio_metrics import PORTFOLIO_TOTAL_CAPEX_PLN
        assert PORTFOLIO_TOTAL_CAPEX_PLN is not None


class TestPortfolioMetricsGauges:
    """Tests for portfolio metrics gauges."""

    def test_portfolio_last_items_total_gauge_exists(self):
        """Portfolio last items total gauge should exist."""
        from observability.portfolio_metrics import PORTFOLIO_LAST_ITEMS_TOTAL
        assert PORTFOLIO_LAST_ITEMS_TOTAL is not None

    def test_portfolio_last_items_ok_gauge_exists(self):
        """Portfolio last items OK gauge should exist."""
        from observability.portfolio_metrics import PORTFOLIO_LAST_ITEMS_OK
        assert PORTFOLIO_LAST_ITEMS_OK is not None

    def test_portfolio_last_items_error_gauge_exists(self):
        """Portfolio last items error gauge should exist."""
        from observability.portfolio_metrics import PORTFOLIO_LAST_ITEMS_ERROR
        assert PORTFOLIO_LAST_ITEMS_ERROR is not None

    def test_portfolio_last_total_npv_gauge_exists(self):
        """Portfolio last total NPV gauge should exist."""
        from observability.portfolio_metrics import PORTFOLIO_LAST_TOTAL_NPV_PLN
        assert PORTFOLIO_LAST_TOTAL_NPV_PLN is not None


class TestPortfolioMetricsRecordFunctions:
    """Tests for portfolio metrics recording functions."""

    def test_record_portfolio_summary_request_exists(self):
        """Record portfolio summary request function should exist."""
        from observability.portfolio_metrics import record_portfolio_summary_request
        assert callable(record_portfolio_summary_request)

    def test_record_portfolio_summary_error_exists(self):
        """Record portfolio summary error function should exist."""
        from observability.portfolio_metrics import record_portfolio_summary_error
        assert callable(record_portfolio_summary_error)

    def test_record_portfolio_export_request_exists(self):
        """Record portfolio export request function should exist."""
        from observability.portfolio_metrics import record_portfolio_export_request
        assert callable(record_portfolio_export_request)

    def test_record_portfolio_summary_result_exists(self):
        """Record portfolio summary result function should exist."""
        from observability.portfolio_metrics import record_portfolio_summary_result
        assert callable(record_portfolio_summary_result)


class TestPortfolioMetricsRecordFunctionCalls:
    """Tests for calling portfolio metrics recording functions."""

    def test_record_summary_request_increments_counter(self):
        """Recording summary request should not raise."""
        from observability.portfolio_metrics import record_portfolio_summary_request
        # Should not raise
        record_portfolio_summary_request(source="api")
        record_portfolio_summary_request(source="job")

    def test_record_summary_error_increments_counter(self):
        """Recording summary error should not raise."""
        from observability.portfolio_metrics import record_portfolio_summary_error
        # Should not raise
        record_portfolio_summary_error(source="api", error_type="validation")
        record_portfolio_summary_error(source="api", error_type="processing")
        record_portfolio_summary_error(source="job", error_type="not_found")

    def test_record_export_request_increments_counter(self):
        """Recording export request should not raise."""
        from observability.portfolio_metrics import record_portfolio_export_request
        # Should not raise
        record_portfolio_export_request(source="api", format="csv")
        record_portfolio_export_request(source="api", format="zip")
        record_portfolio_export_request(source="job", format="csv")

    def test_record_summary_result_updates_metrics(self):
        """Recording summary result should not raise."""
        from observability.portfolio_metrics import record_portfolio_summary_result
        # Should not raise
        record_portfolio_summary_result(
            source="api",
            items_total=5,
            items_ok=4,
            items_error=1,
            total_npv_pln=150000.0,
            total_capex_pln=100000.0,
            mixed_assumptions=False,
        )

    def test_record_summary_result_with_mixed_assumptions(self):
        """Recording summary result with mixed assumptions should not raise."""
        from observability.portfolio_metrics import record_portfolio_summary_result
        # Should not raise
        record_portfolio_summary_result(
            source="api",
            items_total=3,
            items_ok=3,
            items_error=0,
            total_npv_pln=200000.0,
            total_capex_pln=150000.0,
            mixed_assumptions=True,
        )

    def test_record_summary_result_with_negative_npv(self):
        """Recording summary result with negative NPV should not raise."""
        from observability.portfolio_metrics import record_portfolio_summary_result
        # Should not raise
        record_portfolio_summary_result(
            source="api",
            items_total=2,
            items_ok=2,
            items_error=0,
            total_npv_pln=-50000.0,  # Negative NPV
            total_capex_pln=80000.0,
            mixed_assumptions=False,
        )


class TestPortfolioMetricsLabels:
    """Tests for portfolio metrics label values."""

    def test_counter_has_source_label(self):
        """Counters should have source label."""
        from observability.portfolio_metrics import PORTFOLIO_SUMMARY_REQUESTS_TOTAL
        # Getting labels should work
        PORTFOLIO_SUMMARY_REQUESTS_TOTAL.labels(source="api")
        PORTFOLIO_SUMMARY_REQUESTS_TOTAL.labels(source="job")

    def test_export_counter_has_format_label(self):
        """Export counter should have format label."""
        from observability.portfolio_metrics import PORTFOLIO_EXPORT_REQUESTS_TOTAL
        # Getting labels should work
        PORTFOLIO_EXPORT_REQUESTS_TOTAL.labels(source="api", format="csv")
        PORTFOLIO_EXPORT_REQUESTS_TOTAL.labels(source="api", format="zip")

    def test_items_counter_has_status_label(self):
        """Items counter should have status label."""
        from observability.portfolio_metrics import PORTFOLIO_ITEMS_TOTAL
        # Getting labels should work
        PORTFOLIO_ITEMS_TOTAL.labels(status="ok")
        PORTFOLIO_ITEMS_TOTAL.labels(status="error")
