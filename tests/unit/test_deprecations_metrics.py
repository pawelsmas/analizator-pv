"""
Unit tests for deprecation metrics (v2.7.0 PR6).

Tests verify:
- Prometheus metrics are defined
- Metric labels are correct
- Counter increments work
"""

import pytest
import sys
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestMetricDefinitions:
    """Tests for metric definitions."""

    @pytest.fixture
    def prometheus_available(self):
        """Check if prometheus_client is available."""
        try:
            import prometheus_client
            return True
        except ImportError:
            return False

    def test_deprecation_used_total_defined(self, prometheus_available):
        """DEPRECATION_USED_TOTAL counter should be defined."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        from deprecations_usage import DEPRECATION_USED_TOTAL

        assert DEPRECATION_USED_TOTAL is not None

    def test_deprecation_responses_total_defined(self, prometheus_available):
        """DEPRECATION_RESPONSES_TOTAL counter should be defined."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        from deprecations_usage import DEPRECATION_RESPONSES_TOTAL

        assert DEPRECATION_RESPONSES_TOTAL is not None

    def test_compat_legacy_responses_total_defined(self, prometheus_available):
        """COMPAT_LEGACY_RESPONSES_TOTAL counter should be defined."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        from deprecations_usage import COMPAT_LEGACY_RESPONSES_TOTAL

        assert COMPAT_LEGACY_RESPONSES_TOTAL is not None


class TestMetricLabels:
    """Tests for metric label configuration."""

    @pytest.fixture
    def prometheus_available(self):
        """Check if prometheus_client is available."""
        try:
            import prometheus_client
            return True
        except ImportError:
            return False

    def test_deprecation_used_has_field_label(self, prometheus_available):
        """DEPRECATION_USED_TOTAL should have 'field' label."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        from deprecations_usage import DEPRECATION_USED_TOTAL

        # Get the labelnames from the metric
        labelnames = DEPRECATION_USED_TOTAL._labelnames
        assert "field" in labelnames


class TestMarkUsedMetric:
    """Tests for mark_used metric emission."""

    @pytest.fixture
    def prometheus_available(self):
        """Check if prometheus_client is available."""
        try:
            import prometheus_client
            return True
        except ImportError:
            return False

    def test_mark_used_increments_counter(self, prometheus_available):
        """mark_used should increment the counter."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        from deprecations_usage import (
            mark_used,
            clear_request_deprecations,
            DEPRECATION_USED_TOTAL,
        )

        clear_request_deprecations()

        # Get initial value
        initial = DEPRECATION_USED_TOTAL.labels(field="test_field")._value.get()

        # Mark as used
        mark_used("test_field")

        # Get new value
        new = DEPRECATION_USED_TOTAL.labels(field="test_field")._value.get()

        assert new == initial + 1


class TestDeprecationHeadersMetric:
    """Tests for deprecation headers metric emission."""

    @pytest.fixture
    def prometheus_available(self):
        """Check if prometheus_client is available."""
        try:
            import prometheus_client
            return True
        except ImportError:
            return False

    def test_get_headers_increments_responses_counter(self, prometheus_available):
        """get_deprecation_headers should increment responses counter."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        from deprecations_usage import (
            mark_used,
            get_deprecation_headers,
            clear_request_deprecations,
            DEPRECATION_RESPONSES_TOTAL,
        )

        clear_request_deprecations()

        # Get initial value
        initial = DEPRECATION_RESPONSES_TOTAL._value.get()

        # Mark field as used and get headers
        mark_used("test_response_field")
        get_deprecation_headers()

        # Get new value
        new = DEPRECATION_RESPONSES_TOTAL._value.get()

        assert new == initial + 1


class TestCompatLegacyMetric:
    """Tests for compat legacy mode metric."""

    @pytest.fixture
    def prometheus_available(self):
        """Check if prometheus_client is available."""
        try:
            import prometheus_client
            return True
        except ImportError:
            return False

    def test_track_compat_legacy_increments_counter(self, prometheus_available):
        """track_compat_legacy should increment the counter."""
        if not prometheus_available:
            pytest.skip("prometheus_client not installed")

        from deprecations_usage import (
            track_compat_legacy,
            COMPAT_LEGACY_RESPONSES_TOTAL,
        )

        # Get initial value
        initial = COMPAT_LEGACY_RESPONSES_TOTAL._value.get()

        # Track legacy usage
        track_compat_legacy()

        # Get new value
        new = COMPAT_LEGACY_RESPONSES_TOTAL._value.get()

        assert new == initial + 1


class TestAlertRulesFile:
    """Tests for Prometheus alert rules file."""

    def test_alerts_file_exists(self):
        """bess_alerts.yml should exist."""
        alerts_path = Path(__file__).parent.parent.parent / "monitoring" / "prometheus" / "rules" / "bess_alerts.yml"
        assert alerts_path.exists()

    def test_alerts_file_contains_deprecation_alerts(self):
        """bess_alerts.yml should contain deprecation alerts."""
        alerts_path = Path(__file__).parent.parent.parent / "monitoring" / "prometheus" / "rules" / "bess_alerts.yml"
        content = alerts_path.read_text(encoding="utf-8")

        assert "BessDeprecationUsageHigh" in content
        assert "BessLegacyCompatModeHigh" in content
        assert "BessDeprecatedFieldStillUsed" in content

    def test_alerts_use_correct_metric_names(self):
        """Alerts should use correct metric names."""
        alerts_path = Path(__file__).parent.parent.parent / "monitoring" / "prometheus" / "rules" / "bess_alerts.yml"
        content = alerts_path.read_text(encoding="utf-8")

        assert "bess_deprecation_used_total" in content
        assert "bess_compat_legacy_responses_total" in content


class TestGrafanaDashboard:
    """Tests for Grafana dashboard."""

    def test_dashboard_file_exists(self):
        """bess-deprecations.json dashboard should exist."""
        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "monitoring"
            / "grafana"
            / "provisioning"
            / "dashboards"
            / "json"
            / "bess-deprecations.json"
        )
        assert dashboard_path.exists()

    def test_dashboard_is_valid_json(self):
        """Dashboard should be valid JSON."""
        import json

        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "monitoring"
            / "grafana"
            / "provisioning"
            / "dashboards"
            / "json"
            / "bess-deprecations.json"
        )

        with open(dashboard_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "title" in data
        assert "panels" in data

    def test_dashboard_has_deprecation_panels(self):
        """Dashboard should have deprecation tracking panels."""
        import json

        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "monitoring"
            / "grafana"
            / "provisioning"
            / "dashboards"
            / "json"
            / "bess-deprecations.json"
        )

        with open(dashboard_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check for expected panels
        panel_titles = [p.get("title", "") for p in data.get("panels", [])]
        assert any("Deprecated" in t for t in panel_titles)
        assert any("Sunset" in t for t in panel_titles)

    def test_dashboard_uses_correct_metrics(self):
        """Dashboard should query correct metrics."""
        import json

        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "monitoring"
            / "grafana"
            / "provisioning"
            / "dashboards"
            / "json"
            / "bess-deprecations.json"
        )

        with open(dashboard_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "bess_deprecation_used_total" in content
        assert "bess_deprecation_responses_total" in content
        assert "bess_compat_legacy_responses_total" in content
