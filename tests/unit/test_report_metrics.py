"""
Unit tests for report metrics module (v2.4.0 PR6).

Tests verify:
- All counters and histograms are defined correctly
- Helper functions work correctly
- Metric labels are valid
"""

import pytest
import sys

# Skip all tests if prometheus_client is not installed
pytest.importorskip("prometheus_client")

sys.path.insert(0, "services/bess-dispatch")


class TestReportMetricsCounters:
    """Tests for report metrics counters."""

    def test_report_requests_total_defined(self):
        """REPORT_REQUESTS_TOTAL should be defined."""
        from observability.report_metrics import REPORT_REQUESTS_TOTAL
        assert REPORT_REQUESTS_TOTAL is not None
        assert REPORT_REQUESTS_TOTAL._name == "bess_report_requests_total"

    def test_report_requests_total_has_format_label(self):
        """REPORT_REQUESTS_TOTAL should have format label."""
        from observability.report_metrics import REPORT_REQUESTS_TOTAL
        assert "format" in REPORT_REQUESTS_TOTAL._labelnames

    def test_report_profile_requests_total_defined(self):
        """REPORT_PROFILE_REQUESTS_TOTAL should be defined."""
        from observability.report_metrics import REPORT_PROFILE_REQUESTS_TOTAL
        assert REPORT_PROFILE_REQUESTS_TOTAL is not None
        assert REPORT_PROFILE_REQUESTS_TOTAL._name == "bess_report_profile_requests_total"

    def test_report_profile_requests_total_has_profile_label(self):
        """REPORT_PROFILE_REQUESTS_TOTAL should have profile label."""
        from observability.report_metrics import REPORT_PROFILE_REQUESTS_TOTAL
        assert "profile" in REPORT_PROFILE_REQUESTS_TOTAL._labelnames

    def test_report_errors_total_defined(self):
        """REPORT_ERRORS_TOTAL should be defined."""
        from observability.report_metrics import REPORT_ERRORS_TOTAL
        assert REPORT_ERRORS_TOTAL is not None
        assert REPORT_ERRORS_TOTAL._name == "bess_report_errors_total"

    def test_report_errors_total_has_labels(self):
        """REPORT_ERRORS_TOTAL should have format and error_type labels."""
        from observability.report_metrics import REPORT_ERRORS_TOTAL
        assert "format" in REPORT_ERRORS_TOTAL._labelnames
        assert "error_type" in REPORT_ERRORS_TOTAL._labelnames

    def test_portfolio_report_requests_total_defined(self):
        """PORTFOLIO_REPORT_REQUESTS_TOTAL should be defined."""
        from observability.report_metrics import PORTFOLIO_REPORT_REQUESTS_TOTAL
        assert PORTFOLIO_REPORT_REQUESTS_TOTAL is not None
        assert PORTFOLIO_REPORT_REQUESTS_TOTAL._name == "bess_portfolio_report_requests_total"

    def test_portfolio_report_errors_total_defined(self):
        """PORTFOLIO_REPORT_ERRORS_TOTAL should be defined."""
        from observability.report_metrics import PORTFOLIO_REPORT_ERRORS_TOTAL
        assert PORTFOLIO_REPORT_ERRORS_TOTAL is not None
        assert PORTFOLIO_REPORT_ERRORS_TOTAL._name == "bess_portfolio_report_errors_total"

    def test_report_branding_usage_total_defined(self):
        """REPORT_BRANDING_USAGE_TOTAL should be defined."""
        from observability.report_metrics import REPORT_BRANDING_USAGE_TOTAL
        assert REPORT_BRANDING_USAGE_TOTAL is not None
        assert REPORT_BRANDING_USAGE_TOTAL._name == "bess_report_branding_usage_total"


class TestReportMetricsHistograms:
    """Tests for report metrics histograms."""

    def test_report_generation_duration_defined(self):
        """REPORT_GENERATION_DURATION_SECONDS should be defined."""
        from observability.report_metrics import REPORT_GENERATION_DURATION_SECONDS
        assert REPORT_GENERATION_DURATION_SECONDS is not None
        assert REPORT_GENERATION_DURATION_SECONDS._name == "bess_report_generation_duration_seconds"

    def test_report_generation_duration_has_buckets(self):
        """REPORT_GENERATION_DURATION_SECONDS should have proper buckets."""
        from observability.report_metrics import REPORT_GENERATION_DURATION_SECONDS
        # Histogram should have buckets for 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0 seconds
        assert len(REPORT_GENERATION_DURATION_SECONDS._upper_bounds) > 5

    def test_report_size_bytes_defined(self):
        """REPORT_SIZE_BYTES should be defined."""
        from observability.report_metrics import REPORT_SIZE_BYTES
        assert REPORT_SIZE_BYTES is not None
        assert REPORT_SIZE_BYTES._name == "bess_report_size_bytes"

    def test_portfolio_report_items_count_defined(self):
        """PORTFOLIO_REPORT_ITEMS_COUNT should be defined."""
        from observability.report_metrics import PORTFOLIO_REPORT_ITEMS_COUNT
        assert PORTFOLIO_REPORT_ITEMS_COUNT is not None
        assert PORTFOLIO_REPORT_ITEMS_COUNT._name == "bess_portfolio_report_items_count"


class TestReportMetricsGauges:
    """Tests for report metrics gauges."""

    def test_report_last_generation_timestamp_defined(self):
        """REPORT_LAST_GENERATION_TIMESTAMP should be defined."""
        from observability.report_metrics import REPORT_LAST_GENERATION_TIMESTAMP
        assert REPORT_LAST_GENERATION_TIMESTAMP is not None
        assert REPORT_LAST_GENERATION_TIMESTAMP._name == "bess_report_last_generation_timestamp"

    def test_report_last_size_bytes_defined(self):
        """REPORT_LAST_SIZE_BYTES should be defined."""
        from observability.report_metrics import REPORT_LAST_SIZE_BYTES
        assert REPORT_LAST_SIZE_BYTES is not None
        assert REPORT_LAST_SIZE_BYTES._name == "bess_report_last_size_bytes"


class TestReportMetricsHelperFunctions:
    """Tests for report metrics helper functions."""

    def test_track_report_request_function_exists(self):
        """track_report_request function should exist."""
        from observability.report_metrics import track_report_request
        assert callable(track_report_request)

    def test_track_report_request_increments_counters(self):
        """track_report_request should increment counters."""
        from observability import report_metrics

        # Get initial values
        initial_requests = report_metrics.REPORT_REQUESTS_TOTAL.labels(format="pdf")._value._value
        initial_profile = report_metrics.REPORT_PROFILE_REQUESTS_TOTAL.labels(profile="engineering")._value._value

        # Call function
        report_metrics.track_report_request("pdf", "engineering")

        # Check incremented
        assert report_metrics.REPORT_REQUESTS_TOTAL.labels(format="pdf")._value._value == initial_requests + 1
        assert report_metrics.REPORT_PROFILE_REQUESTS_TOTAL.labels(profile="engineering")._value._value == initial_profile + 1

    def test_track_report_error_function_exists(self):
        """track_report_error function should exist."""
        from observability.report_metrics import track_report_error
        assert callable(track_report_error)

    def test_track_report_error_increments_counter(self):
        """track_report_error should increment error counter."""
        from observability import report_metrics

        initial = report_metrics.REPORT_ERRORS_TOTAL.labels(format="xlsx", error_type="not_found")._value._value
        report_metrics.track_report_error("xlsx", "not_found")

        assert report_metrics.REPORT_ERRORS_TOTAL.labels(format="xlsx", error_type="not_found")._value._value == initial + 1

    def test_track_report_branding_function_exists(self):
        """track_report_branding function should exist."""
        from observability.report_metrics import track_report_branding
        assert callable(track_report_branding)

    def test_track_report_branding_with_client_name(self):
        """track_report_branding should increment counter for client_name."""
        from observability import report_metrics

        initial = report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="client_name")._value._value
        report_metrics.track_report_branding(client_name="Test Corp")

        assert report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="client_name")._value._value == initial + 1

    def test_track_report_branding_with_multiple_fields(self):
        """track_report_branding should increment counters for all provided fields."""
        from observability import report_metrics

        initial_client = report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="client_name")._value._value
        initial_site = report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="site_name")._value._value

        report_metrics.track_report_branding(client_name="Test", site_name="Site A")

        assert report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="client_name")._value._value == initial_client + 1
        assert report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="site_name")._value._value == initial_site + 1

    def test_track_report_branding_with_empty_fields(self):
        """track_report_branding should not increment for None/empty fields."""
        from observability import report_metrics

        initial = report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="notes")._value._value
        report_metrics.track_report_branding(notes=None)

        # Should not increment because notes is None
        assert report_metrics.REPORT_BRANDING_USAGE_TOTAL.labels(field="notes")._value._value == initial

    def test_track_report_generation_function_exists(self):
        """track_report_generation function should exist."""
        from observability.report_metrics import track_report_generation
        assert callable(track_report_generation)

    def test_track_report_generation_updates_metrics(self):
        """track_report_generation should update histogram and gauges."""
        from observability import report_metrics

        report_metrics.track_report_generation("zip", 1.5, 50000)

        # Check gauge was set (last size)
        last_size = report_metrics.REPORT_LAST_SIZE_BYTES.labels(format="zip")._value._value
        assert last_size == 50000

    def test_track_portfolio_report_request_function_exists(self):
        """track_portfolio_report_request function should exist."""
        from observability.report_metrics import track_portfolio_report_request
        assert callable(track_portfolio_report_request)

    def test_track_portfolio_report_request_increments_counter(self):
        """track_portfolio_report_request should increment counter."""
        from observability import report_metrics

        initial = report_metrics.PORTFOLIO_REPORT_REQUESTS_TOTAL._value._value
        report_metrics.track_portfolio_report_request(5)

        assert report_metrics.PORTFOLIO_REPORT_REQUESTS_TOTAL._value._value == initial + 1

    def test_track_portfolio_report_error_function_exists(self):
        """track_portfolio_report_error function should exist."""
        from observability.report_metrics import track_portfolio_report_error
        assert callable(track_portfolio_report_error)

    def test_track_portfolio_report_error_increments_counter(self):
        """track_portfolio_report_error should increment error counter."""
        from observability import report_metrics

        initial = report_metrics.PORTFOLIO_REPORT_ERRORS_TOTAL.labels(error_type="validation")._value._value
        report_metrics.track_portfolio_report_error("validation")

        assert report_metrics.PORTFOLIO_REPORT_ERRORS_TOTAL.labels(error_type="validation")._value._value == initial + 1


class TestReportMetricsLabels:
    """Tests for metric label values."""

    def test_format_labels_are_valid(self):
        """Format labels should be valid for PDF, XLSX, ZIP."""
        from observability.report_metrics import REPORT_REQUESTS_TOTAL

        # These should not raise errors
        REPORT_REQUESTS_TOTAL.labels(format="pdf")
        REPORT_REQUESTS_TOTAL.labels(format="xlsx")
        REPORT_REQUESTS_TOTAL.labels(format="zip")

    def test_profile_labels_are_valid(self):
        """Profile labels should be valid for client and engineering."""
        from observability.report_metrics import REPORT_PROFILE_REQUESTS_TOTAL

        # These should not raise errors
        REPORT_PROFILE_REQUESTS_TOTAL.labels(profile="client")
        REPORT_PROFILE_REQUESTS_TOTAL.labels(profile="engineering")

    def test_error_type_labels_are_valid(self):
        """Error type labels should be valid."""
        from observability.report_metrics import REPORT_ERRORS_TOTAL

        # These should not raise errors
        REPORT_ERRORS_TOTAL.labels(format="pdf", error_type="not_found")
        REPORT_ERRORS_TOTAL.labels(format="xlsx", error_type="generation")
        REPORT_ERRORS_TOTAL.labels(format="zip", error_type="validation")

    def test_branding_field_labels_are_valid(self):
        """Branding field labels should be valid."""
        from observability.report_metrics import REPORT_BRANDING_USAGE_TOTAL

        # These should not raise errors
        REPORT_BRANDING_USAGE_TOTAL.labels(field="client_name")
        REPORT_BRANDING_USAGE_TOTAL.labels(field="site_name")
        REPORT_BRANDING_USAGE_TOTAL.labels(field="report_title")
        REPORT_BRANDING_USAGE_TOTAL.labels(field="notes")
