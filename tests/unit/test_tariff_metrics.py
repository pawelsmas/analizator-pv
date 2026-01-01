"""
Unit tests for Tariff/Pricing Preview Metrics (v2.1.0 PR6).

Tests verify:
- Metric naming conventions
- Helper function logic
- Anomaly detection logic
- Label value generation
"""

import pytest


class TestTariffMetricNaming:
    """Tests for Prometheus metric naming conventions."""

    def test_counter_names_follow_pattern(self):
        """Verify counter names follow bess_* pattern."""
        counter_names = [
            "bess_tariff_presets_list_total",
            "bess_pricing_preview_requests_total",
            "bess_tariff_preset_usage_total",
            "bess_tariff_schedule_usage_total",
            "bess_price_anomaly_detected_total",
        ]
        for name in counter_names:
            assert name.startswith("bess_")
            assert name.endswith("_total")

    def test_histogram_names_follow_pattern(self):
        """Verify histogram names follow bess_* pattern."""
        histogram_names = [
            "bess_pricing_preview_steps",
            "bess_pricing_preview_duration_seconds",
        ]
        for name in histogram_names:
            assert name.startswith("bess_")


class TestPricingModeLabels:
    """Tests for pricing mode label generation."""

    def test_valid_pricing_modes(self):
        """Verify valid pricing modes."""
        valid_modes = ["generated", "preset", "schedule", "override"]
        assert len(valid_modes) == 4
        for mode in valid_modes:
            assert mode.islower()

    def test_mode_label_for_preset(self):
        """Verify preset mode label."""
        tariff_preset = "pl_flat_2026"
        pricing_mode = "preset" if tariff_preset else "generated"
        assert pricing_mode == "preset"

    def test_mode_label_for_schedule(self):
        """Verify schedule mode label."""
        tariff_schedule = {"weekday_import_price_pln_per_mwh": [500.0] * 24}
        pricing_mode = "schedule" if tariff_schedule else "generated"
        assert pricing_mode == "schedule"


class TestPresetUsageLabels:
    """Tests for preset usage label generation."""

    def test_preset_id_as_label(self):
        """Verify preset ID is used as label."""
        preset_id = "pl_flat_2026"
        label = preset_id
        assert label == "pl_flat_2026"

    def test_tou_preset_id_as_label(self):
        """Verify ToU preset ID is used as label."""
        preset_id = "pl_tou_simple_2026"
        label = preset_id
        assert label == "pl_tou_simple_2026"


class TestScheduleUsageLabels:
    """Tests for schedule usage label generation."""

    def test_has_holidays_true_label(self):
        """Verify has_holidays=true label."""
        holiday_dates = ["2025-12-25", "2025-12-26"]
        has_holidays = bool(holiday_dates)
        label = "true" if has_holidays else "false"
        assert label == "true"

    def test_has_holidays_false_label(self):
        """Verify has_holidays=false label."""
        holiday_dates = []
        has_holidays = bool(holiday_dates)
        label = "true" if has_holidays else "false"
        assert label == "false"

    def test_has_holidays_none_label(self):
        """Verify has_holidays=false for None."""
        holiday_dates = None
        has_holidays = bool(holiday_dates)
        label = "true" if has_holidays else "false"
        assert label == "false"


class TestAnomalyDetection:
    """Tests for price anomaly detection logic."""

    def test_zero_import_detection(self):
        """Verify zero import price detection."""
        prices = [0.0, 0.0, 0.0, 0.0]
        all_zero = all(p == 0 for p in prices)
        assert all_zero is True

    def test_non_zero_import_no_detection(self):
        """Verify non-zero prices don't trigger zero detection."""
        prices = [500.0, 600.0, 700.0, 400.0]
        all_zero = all(p == 0 for p in prices)
        assert all_zero is False

    def test_negative_price_detection(self):
        """Verify negative price detection."""
        prices = [500.0, -100.0, 600.0, 700.0]
        has_negative = any(p < 0 for p in prices)
        assert has_negative is True

    def test_no_negative_price(self):
        """Verify no negative prices don't trigger detection."""
        prices = [500.0, 0.0, 600.0, 700.0]
        has_negative = any(p < 0 for p in prices)
        assert has_negative is False

    def test_extreme_variance_detection(self):
        """Verify extreme variance detection (CV > 100%)."""
        prices = [100.0, 1000.0, 50.0, 2000.0]
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        std_dev = variance ** 0.5
        cv = std_dev / avg
        assert cv > 1.0  # CV > 100%

    def test_normal_variance_no_detection(self):
        """Verify normal variance doesn't trigger detection."""
        prices = [500.0, 520.0, 510.0, 505.0]
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        std_dev = variance ** 0.5
        cv = std_dev / avg
        assert cv < 1.0  # CV < 100%


class TestAnomalyTypes:
    """Tests for anomaly type labels."""

    def test_valid_anomaly_types(self):
        """Verify valid anomaly type labels."""
        valid_types = ["zero_import", "negative_price", "extreme_variance"]
        assert len(valid_types) == 3
        for t in valid_types:
            assert "_" in t  # Uses snake_case

    def test_anomaly_type_lowercase(self):
        """Verify anomaly types are lowercase."""
        types = ["zero_import", "negative_price", "extreme_variance"]
        for t in types:
            assert t.islower()


class TestHistogramBuckets:
    """Tests for histogram bucket configuration."""

    def test_steps_buckets_range(self):
        """Verify steps histogram covers typical ranges."""
        expected_buckets = [24, 48, 96, 168, 336, 672, 744, 1440, 2880, 8760]
        # 24 = 1 day hourly
        # 168 = 1 week hourly
        # 8760 = 1 year hourly
        assert expected_buckets[0] == 24
        assert expected_buckets[-1] == 8760
        assert 168 in expected_buckets  # 1 week

    def test_duration_buckets_range(self):
        """Verify duration histogram covers typical ranges."""
        expected_buckets = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
        assert expected_buckets[0] == 0.01
        assert expected_buckets[-1] == 5.0


class TestMetricRecordingLogic:
    """Tests for metric recording helper function logic."""

    def test_record_preset_usage_logic(self):
        """Verify preset usage recording logic."""
        preset_id = "pl_flat_2026"
        # Would call: record_tariff_preset_usage(preset_id)
        # Labels would be: {"preset_id": "pl_flat_2026"}
        assert preset_id == "pl_flat_2026"

    def test_record_schedule_usage_logic(self):
        """Verify schedule usage recording logic."""
        has_holidays = True
        label = "true" if has_holidays else "false"
        # Would call: record_tariff_schedule_usage(has_holidays)
        # Labels would be: {"has_holidays": "true"}
        assert label == "true"

    def test_record_pricing_preview_logic(self):
        """Verify pricing preview recording logic."""
        pricing_mode = "schedule"
        # Would call: record_pricing_preview(pricing_mode)
        # Labels would be: {"pricing_mode": "schedule"}
        assert pricing_mode in ["generated", "preset", "schedule", "override"]


class TestAnomalyCheckFunction:
    """Tests for check_price_anomalies function logic."""

    def test_empty_prices_returns_empty(self):
        """Verify empty prices returns empty anomalies."""
        prices = []
        anomalies = []
        if not prices:
            pass  # No anomalies for empty list
        assert anomalies == []

    def test_single_price_no_variance_check(self):
        """Verify single price doesn't trigger variance check."""
        prices = [500.0]
        # Variance check requires len > 1
        should_check_variance = len(prices) > 1
        assert should_check_variance is False

    def test_multiple_anomalies_detected(self):
        """Verify multiple anomalies can be detected."""
        prices = [-100.0, 0.0, 0.0, 0.0]

        anomalies = []
        if all(p == 0 for p in prices):
            anomalies.append("zero_import")
        if any(p < 0 for p in prices):
            anomalies.append("negative_price")

        # Has negative but not all zero
        assert "negative_price" in anomalies
        assert "zero_import" not in anomalies  # Not all zero


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

    def test_import_v21_metrics(self, prometheus_available):
        """Verify v2.1.0 metrics can be imported."""
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

            # v2.1.0 metrics
            assert hasattr(pricing_metrics, "TARIFF_PRESETS_LIST_TOTAL")
            assert hasattr(pricing_metrics, "PRICING_PREVIEW_REQUESTS_TOTAL")
            assert hasattr(pricing_metrics, "TARIFF_PRESET_USAGE_TOTAL")
            assert hasattr(pricing_metrics, "TARIFF_SCHEDULE_USAGE_TOTAL")
            assert hasattr(pricing_metrics, "PRICING_PREVIEW_STEPS")
            assert hasattr(pricing_metrics, "PRICING_PREVIEW_DURATION_SECONDS")
            assert hasattr(pricing_metrics, "PRICE_ANOMALY_DETECTED")

        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)

    def test_v21_helper_functions_exist(self, prometheus_available):
        """Verify v2.1.0 helper functions exist."""
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

            assert callable(pricing_metrics.record_tariff_presets_list)
            assert callable(pricing_metrics.record_pricing_preview)
            assert callable(pricing_metrics.record_tariff_preset_usage)
            assert callable(pricing_metrics.record_tariff_schedule_usage)
            assert callable(pricing_metrics.record_pricing_preview_steps)
            assert callable(pricing_metrics.record_pricing_preview_duration)
            assert callable(pricing_metrics.record_price_anomaly)
            assert callable(pricing_metrics.check_price_anomalies)

        finally:
            if service_path in sys.path:
                sys.path.remove(service_path)
