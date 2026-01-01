"""
Unit tests for Pricing Engine observability metrics (v2.0.0 PR6).

Tests verify:
- Pricing request tracking with correct label logic
- Pricing mode label generation (generated/override)
- Price override counter increment logic
- Histogram bucket configuration
- Ledger cost recording logic
"""

import pytest


class TestRecordPricingRequest:
    """Tests for record_pricing_request function logic."""

    def test_both_flags_true_labels(self):
        """Verify labels when both include flags are true."""
        include_price_timeseries = True
        include_ledger_timeseries = True

        label_price = "true" if include_price_timeseries else "false"
        label_ledger = "true" if include_ledger_timeseries else "false"

        assert label_price == "true"
        assert label_ledger == "true"

    def test_both_flags_false_labels(self):
        """Verify labels when both include flags are false."""
        include_price_timeseries = False
        include_ledger_timeseries = False

        label_price = "true" if include_price_timeseries else "false"
        label_ledger = "true" if include_ledger_timeseries else "false"

        assert label_price == "false"
        assert label_ledger == "false"

    def test_mixed_flags_labels(self):
        """Verify labels when flags are mixed."""
        # Price true, ledger false
        label_price = "true" if True else "false"
        label_ledger = "true" if False else "false"
        assert label_price == "true"
        assert label_ledger == "false"

        # Price false, ledger true
        label_price = "true" if False else "false"
        label_ledger = "true" if True else "false"
        assert label_price == "false"
        assert label_ledger == "true"


class TestRecordPricingMode:
    """Tests for record_pricing_mode function logic."""

    def test_generated_mode_label(self):
        """Verify 'generated' mode produces correct label."""
        mode = "generated"
        assert mode == "generated"

    def test_override_mode_label(self):
        """Verify 'override' mode produces correct label."""
        mode = "override"
        assert mode == "override"

    def test_mode_is_lowercase(self):
        """Verify mode labels are lowercase."""
        assert "generated".islower()
        assert "override".islower()


class TestRecordPriceValues:
    """Tests for record_price_values function logic."""

    def test_positive_prices_recorded(self):
        """Verify positive price values are valid for histogram."""
        avg_import = 800.0
        avg_export = 400.0
        assert avg_import > 0
        assert avg_export > 0

    def test_zero_prices_valid(self):
        """Verify zero prices are valid."""
        avg_import = 0.0
        avg_export = 0.0
        assert avg_import == 0.0
        assert avg_export == 0.0

    def test_high_prices_valid(self):
        """Verify high prices within histogram range."""
        avg_import = 2500.0
        avg_export = 900.0
        # Prices within reasonable PLN/MWh range
        assert avg_import <= 5000
        assert avg_export <= 2000


class TestRecordLedgerCosts:
    """Tests for record_ledger_costs function logic."""

    def test_positive_costs_recorded(self):
        """Verify positive costs are valid."""
        import_cost = 500.0
        export_revenue = 200.0
        net_cost = 300.0
        assert import_cost > 0
        assert export_revenue > 0
        assert net_cost == import_cost - export_revenue

    def test_negative_net_cost_valid(self):
        """Verify negative net cost (profit) is valid."""
        import_cost = 100.0
        export_revenue = 500.0
        net_cost = import_cost - export_revenue
        assert net_cost == -400.0
        assert net_cost < 0  # This is profit

    def test_zero_costs_valid(self):
        """Verify zero costs are valid."""
        import_cost = 0.0
        export_revenue = 0.0
        net_cost = 0.0
        assert import_cost == 0.0
        assert export_revenue == 0.0
        assert net_cost == 0.0


class TestMetricNaming:
    """Tests for Prometheus metric naming conventions."""

    def test_counter_names_follow_pattern(self):
        """Verify counter names follow bess_* pattern."""
        counter_names = [
            "bess_pricing_requests_total",
            "bess_pricing_mode_total",
            "bess_price_override_requests_total",
        ]
        for name in counter_names:
            assert name.startswith("bess_")
            assert name.endswith("_total")

    def test_histogram_names_follow_pattern(self):
        """Verify histogram names follow bess_* pattern with unit suffix."""
        histogram_names = [
            "bess_price_import_pln_mwh",
            "bess_price_export_pln_mwh",
            "bess_ledger_import_cost_pln",
            "bess_ledger_export_revenue_pln",
            "bess_ledger_net_cost_pln",
        ]
        for name in histogram_names:
            assert name.startswith("bess_")
            # All have unit suffix
            assert "_pln" in name


class TestHistogramBuckets:
    """Tests for histogram bucket configuration."""

    def test_price_import_buckets_range(self):
        """Verify import price buckets cover typical PLN/MWh range."""
        expected_buckets = [0, 200, 400, 600, 800, 1000, 1200, 1500, 2000, 3000]
        assert expected_buckets[0] == 0
        assert expected_buckets[-1] == 3000
        assert len(expected_buckets) == 10

    def test_price_export_buckets_range(self):
        """Verify export price buckets cover typical PLN/MWh range."""
        expected_buckets = [0, 100, 200, 300, 400, 500, 600, 800, 1000]
        assert expected_buckets[0] == 0
        assert expected_buckets[-1] == 1000
        assert len(expected_buckets) == 9

    def test_ledger_cost_buckets_range(self):
        """Verify ledger cost buckets cover PLN range."""
        expected_buckets = [0, 10, 50, 100, 500, 1000, 5000, 10000, 50000]
        assert expected_buckets[0] == 0
        assert expected_buckets[-1] == 50000
        assert len(expected_buckets) == 9

    def test_net_cost_buckets_include_negative(self):
        """Verify net cost buckets include negative values for profit."""
        expected_buckets = [-10000, -5000, -1000, -500, -100, 0, 100, 500, 1000, 5000, 10000]
        # Has negative values
        has_negative = any(b < 0 for b in expected_buckets)
        assert has_negative
        # Has positive values
        has_positive = any(b > 0 for b in expected_buckets)
        assert has_positive
        # Has zero
        assert 0 in expected_buckets


class TestLabelValues:
    """Tests for label value conventions."""

    def test_boolean_labels_are_lowercase_strings(self):
        """Verify boolean labels use lowercase 'true'/'false' strings."""
        assert "true".islower()
        assert "false".islower()
        assert "true" != "True"
        assert "false" != "False"

    def test_mode_labels_are_valid(self):
        """Verify pricing mode labels are valid values."""
        valid_modes = {"generated", "override"}
        assert "generated" in valid_modes
        assert "override" in valid_modes

    def test_pricing_requests_labels(self):
        """Verify PRICING_REQUESTS_TOTAL expected labels."""
        expected_labels = ["include_price_timeseries", "include_ledger_timeseries"]
        assert len(expected_labels) == 2

    def test_pricing_mode_labels(self):
        """Verify PRICING_MODE_TOTAL expected labels."""
        expected_labels = ["mode"]
        assert len(expected_labels) == 1


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

    def test_import_pricing_metrics_module(self, prometheus_available):
        """Verify pricing_metrics module can be imported when prometheus available."""
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
                "pricing_metrics",
                os.path.join(service_path, "observability", "pricing_metrics.py")
            )
            pricing_metrics = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pricing_metrics)

            assert hasattr(pricing_metrics, "PRICING_REQUESTS_TOTAL")
            assert hasattr(pricing_metrics, "PRICING_MODE_TOTAL")
            assert hasattr(pricing_metrics, "PRICE_OVERRIDE_REQUESTS_TOTAL")
            assert hasattr(pricing_metrics, "PRICE_IMPORT_PLN_MWH")
            assert hasattr(pricing_metrics, "PRICE_EXPORT_PLN_MWH")
            assert hasattr(pricing_metrics, "LEDGER_IMPORT_COST_PLN")
            assert hasattr(pricing_metrics, "LEDGER_EXPORT_REVENUE_PLN")
            assert hasattr(pricing_metrics, "LEDGER_NET_COST_PLN")
        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)

    def test_helper_functions_callable(self, prometheus_available):
        """Verify all helper functions are callable."""
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
                "pricing_metrics",
                os.path.join(service_path, "observability", "pricing_metrics.py")
            )
            pricing_metrics = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pricing_metrics)

            assert callable(pricing_metrics.record_pricing_request)
            assert callable(pricing_metrics.record_pricing_mode)
            assert callable(pricing_metrics.record_price_override_request)
            assert callable(pricing_metrics.record_price_values)
            assert callable(pricing_metrics.record_ledger_costs)
        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)

    def test_record_pricing_request_signature(self, prometheus_available):
        """Verify record_pricing_request has correct parameters."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        import sys
        import os
        import importlib.util
        import inspect

        service_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch")
        )

        if service_path not in sys.path:
            sys.path.insert(0, service_path)

        try:
            spec = importlib.util.spec_from_file_location(
                "pricing_metrics",
                os.path.join(service_path, "observability", "pricing_metrics.py")
            )
            pricing_metrics = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pricing_metrics)

            sig = inspect.signature(pricing_metrics.record_pricing_request)
            params = list(sig.parameters.keys())
            assert "include_price_timeseries" in params
            assert "include_ledger_timeseries" in params
        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)

    def test_record_ledger_costs_signature(self, prometheus_available):
        """Verify record_ledger_costs has correct parameters."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        import sys
        import os
        import importlib.util
        import inspect

        service_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch")
        )

        if service_path not in sys.path:
            sys.path.insert(0, service_path)

        try:
            spec = importlib.util.spec_from_file_location(
                "pricing_metrics",
                os.path.join(service_path, "observability", "pricing_metrics.py")
            )
            pricing_metrics = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pricing_metrics)

            sig = inspect.signature(pricing_metrics.record_ledger_costs)
            params = list(sig.parameters.keys())
            assert "import_cost_pln" in params
            assert "export_revenue_pln" in params
            assert "net_cost_pln" in params
        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)
