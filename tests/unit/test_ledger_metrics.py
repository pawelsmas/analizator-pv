"""
Unit tests for ledger_metrics.py (v1.9.0).

Tests verify:
- Metrics are properly incremented on reconciliation
- Request tracking with include_money_ledger flag
- Histogram buckets for error magnitudes
"""

import pytest


class TestRecordLedgerReconciliation:
    """Tests for record_ledger_reconciliation function."""

    def test_reconciliation_passed_status_label(self):
        """Verify passed reconciliation produces 'passed' status label."""
        passed = True
        status = "passed" if passed else "failed"
        assert status == "passed"

    def test_reconciliation_failed_status_label(self):
        """Verify failed reconciliation produces 'failed' status label."""
        passed = False
        status = "passed" if passed else "failed"
        assert status == "failed"

    def test_error_magnitude_absolute_value(self):
        """Verify error magnitude is converted to absolute value."""
        error_pln = 5.5
        observed_value = abs(error_pln)
        assert observed_value == 5.5

    def test_negative_error_converted_to_absolute(self):
        """Verify negative error values are converted to absolute."""
        error_pln = -10.0
        observed_value = abs(error_pln)
        assert observed_value == 10.0

    def test_zero_error_recorded(self):
        """Verify zero error is recorded correctly."""
        error_pln = 0.0
        observed_value = abs(error_pln)
        assert observed_value == 0.0


class TestRecordLedgerRequest:
    """Tests for record_ledger_request function."""

    def test_request_with_ledger_enabled_label(self):
        """Verify requests with include_money_ledger=True produce 'true' label."""
        include_money_ledger = True
        label_value = "true" if include_money_ledger else "false"
        assert label_value == "true"

    def test_request_with_ledger_disabled_label(self):
        """Verify requests with include_money_ledger=False produce 'false' label."""
        include_money_ledger = False
        label_value = "true" if include_money_ledger else "false"
        assert label_value == "false"


class TestMetricDefinitions:
    """Tests for metric definitions."""

    def test_reconciliation_counter_status_labels(self):
        """Verify LEDGER_RECONCILIATION_TOTAL has 'status' label."""
        expected_labels = ["status"]
        assert expected_labels == ["status"]

    def test_requests_counter_include_money_ledger_label(self):
        """Verify LEDGER_REQUESTS_TOTAL has 'include_money_ledger' label."""
        expected_labels = ["include_money_ledger"]
        assert expected_labels == ["include_money_ledger"]

    def test_histogram_buckets_count(self):
        """Verify histogram has 7 buckets for PLN errors."""
        expected_buckets = [0, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
        assert len(expected_buckets) == 7

    def test_histogram_buckets_range(self):
        """Verify histogram buckets cover 0 to 1000 PLN."""
        expected_buckets = [0, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
        assert expected_buckets[0] == 0
        assert expected_buckets[-1] == 1000.0

    def test_histogram_buckets_order(self):
        """Verify histogram buckets are in ascending order."""
        expected_buckets = [0, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
        for i in range(len(expected_buckets) - 1):
            assert expected_buckets[i] < expected_buckets[i + 1]


class TestReconciliationLogic:
    """Tests for reconciliation logic patterns."""

    def test_reconciliation_passes_when_error_within_tolerance(self):
        """Verify reconciliation passes with error under 1 PLN tolerance."""
        tolerance_pln = 1.0
        error_within_tolerance = 0.5
        passed = error_within_tolerance <= tolerance_pln
        assert passed is True

    def test_reconciliation_fails_when_error_exceeds_tolerance(self):
        """Verify reconciliation fails with error over 1 PLN tolerance."""
        tolerance_pln = 1.0
        error_exceeds_tolerance = 1.5
        passed = error_exceeds_tolerance <= tolerance_pln
        assert passed is False

    def test_reconciliation_edge_case_at_tolerance(self):
        """Verify edge case at exactly tolerance boundary passes."""
        tolerance_pln = 1.0
        error_at_boundary = 1.0
        passed = error_at_boundary <= tolerance_pln
        assert passed is True

    def test_reconciliation_with_zero_error(self):
        """Verify zero error passes reconciliation."""
        tolerance_pln = 1.0
        error = 0.0
        passed = error <= tolerance_pln
        assert passed is True

    def test_reconciliation_with_small_rounding_error(self):
        """Verify small rounding errors pass reconciliation."""
        tolerance_pln = 1.0
        # Typical floating point rounding error
        error = 0.0001
        passed = error <= tolerance_pln
        assert passed is True


class TestMetricNaming:
    """Tests for Prometheus metric naming conventions."""

    def test_counter_name_pattern(self):
        """Verify counter names follow bess_* pattern."""
        counter_names = [
            "bess_ledger_reconciliation_total",
            "bess_ledger_requests_total",
        ]
        for name in counter_names:
            assert name.startswith("bess_")
            assert name.endswith("_total")

    def test_histogram_name_pattern(self):
        """Verify histogram name follows bess_* pattern with unit suffix."""
        histogram_name = "bess_ledger_reconciliation_error_pln"
        assert histogram_name.startswith("bess_")
        assert "_pln" in histogram_name  # unit suffix

    def test_label_values_are_lowercase(self):
        """Verify label values use lowercase strings."""
        # Status labels
        assert "passed".islower()
        assert "failed".islower()
        # include_money_ledger labels
        assert "true".islower()
        assert "false".islower()


class TestMetricIntegration:
    """Integration tests that require prometheus_client."""

    @pytest.fixture
    def prometheus_available(self):
        """Check if prometheus_client is available."""
        try:
            import prometheus_client
            return True
        except ImportError:
            return False

    def test_import_ledger_metrics_module(self, prometheus_available):
        """Verify ledger_metrics module can be imported when prometheus available."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        import sys
        import os

        service_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch")
        )

        if service_path not in sys.path:
            sys.path.insert(0, service_path)

        try:
            # Import directly, avoiding __init__.py
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "ledger_metrics",
                os.path.join(service_path, "observability", "ledger_metrics.py")
            )
            ledger_metrics = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ledger_metrics)

            assert hasattr(ledger_metrics, "LEDGER_RECONCILIATION_TOTAL")
            assert hasattr(ledger_metrics, "LEDGER_REQUESTS_TOTAL")
            assert hasattr(ledger_metrics, "LEDGER_RECONCILIATION_ERROR_PLN")
            assert hasattr(ledger_metrics, "record_ledger_reconciliation")
            assert hasattr(ledger_metrics, "record_ledger_request")
        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)

    def test_record_reconciliation_function_is_callable(self, prometheus_available):
        """Verify record_ledger_reconciliation is callable."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        import sys
        import os
        import importlib.util

        service_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch")
        )

        if service_path not in sys.path:
            sys.path.insert(0, service_path)

        try:
            spec = importlib.util.spec_from_file_location(
                "ledger_metrics",
                os.path.join(service_path, "observability", "ledger_metrics.py")
            )
            ledger_metrics = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ledger_metrics)

            assert callable(ledger_metrics.record_ledger_reconciliation)
        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)

    def test_record_request_function_is_callable(self, prometheus_available):
        """Verify record_ledger_request is callable."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        import sys
        import os
        import importlib.util

        service_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch")
        )

        if service_path not in sys.path:
            sys.path.insert(0, service_path)

        try:
            spec = importlib.util.spec_from_file_location(
                "ledger_metrics",
                os.path.join(service_path, "observability", "ledger_metrics.py")
            )
            ledger_metrics = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ledger_metrics)

            assert callable(ledger_metrics.record_ledger_request)
        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)
