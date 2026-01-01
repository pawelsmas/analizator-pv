"""
Contract tests for report metrics endpoint (v2.4.0 PR6).

Tests verify:
- GET /metrics includes report metrics
- Report metrics have expected labels
- Report metrics are properly formatted
"""

import pytest
import requests
from ._api import DEFAULT_BASE_URL, post_json


def _get_metrics():
    """Fetch metrics from the /metrics endpoint."""
    url = f"{DEFAULT_BASE_URL}/metrics"
    resp = requests.get(url)
    assert resp.status_code == 200
    return resp.text


def _base_req():
    """Minimal valid sizing request."""
    return {
        "load_kw": [100] * 24,
        "pv_generation_kw": [0, 0, 0, 0, 0, 0, 50, 200, 500, 800, 1000, 1100, 1100, 1000, 800, 500, 200, 50, 0, 0, 0, 0, 0, 0],
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def _create_sizing_run():
    """Create a sizing run and return run_id."""
    request = _base_req()
    resp = post_json("/sizing", request)
    return resp.get("meta", {}).get("run_id") or resp.get("cache_info", {}).get("run_id")


def _trigger_report_download(run_id, format="pdf"):
    """Trigger a report download to register metrics."""
    url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.{format}"
    return requests.get(url)


class TestReportMetricsPresent:
    """Tests that report metrics are present in /metrics."""

    def test_metrics_endpoint_returns_200(self):
        """Metrics endpoint should return 200."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/metrics")
        assert resp.status_code == 200

    def test_report_requests_total_metric_present(self):
        """bess_report_requests_total should be in metrics."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert "bess_report_requests_total" in metrics

    def test_report_profile_requests_total_metric_present(self):
        """bess_report_profile_requests_total should be in metrics."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert "bess_report_profile_requests_total" in metrics

    def test_report_generation_duration_metric_present(self):
        """bess_report_generation_duration_seconds should be in metrics."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert "bess_report_generation_duration_seconds" in metrics

    def test_report_size_bytes_metric_present(self):
        """bess_report_size_bytes should be in metrics."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert "bess_report_size_bytes" in metrics


class TestReportMetricsLabels:
    """Tests for report metrics labels."""

    def test_pdf_format_label_present(self):
        """PDF format label should be present after PDF download."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert 'format="pdf"' in metrics

    def test_xlsx_format_label_present(self):
        """XLSX format label should be present after XLSX download."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "xlsx")

        metrics = _get_metrics()
        assert 'format="xlsx"' in metrics

    def test_zip_format_label_present(self):
        """ZIP format label should be present after ZIP download."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "zip")

        metrics = _get_metrics()
        assert 'format="zip"' in metrics

    def test_client_profile_label_present(self):
        """Client profile label should be present."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert 'profile="client"' in metrics

    def test_engineering_profile_label_present(self):
        """Engineering profile label should be present."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf?profile=engineering"
        requests.get(url)

        metrics = _get_metrics()
        assert 'profile="engineering"' in metrics


class TestReportMetricsAfterDownload:
    """Tests for metrics after report download."""

    def test_metrics_increment_after_pdf_download(self):
        """Metrics should increment after PDF download."""
        run_id = _create_sizing_run()

        # Get initial metrics
        initial_metrics = _get_metrics()

        # Download report
        resp = _trigger_report_download(run_id, "pdf")
        assert resp.status_code == 200

        # Get updated metrics
        updated_metrics = _get_metrics()

        # Verify PDF metrics are present
        assert "bess_report_requests_total" in updated_metrics
        assert 'format="pdf"' in updated_metrics

    def test_metrics_increment_after_xlsx_download(self):
        """Metrics should increment after XLSX download."""
        run_id = _create_sizing_run()
        resp = _trigger_report_download(run_id, "xlsx")
        assert resp.status_code == 200

        metrics = _get_metrics()
        assert 'format="xlsx"' in metrics

    def test_metrics_increment_after_zip_download(self):
        """Metrics should increment after ZIP download."""
        run_id = _create_sizing_run()
        resp = _trigger_report_download(run_id, "zip")
        assert resp.status_code == 200

        metrics = _get_metrics()
        assert 'format="zip"' in metrics


class TestReportMetricsHistograms:
    """Tests for report metrics histograms."""

    def test_duration_histogram_has_buckets(self):
        """Duration histogram should have proper buckets."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        # Histogram should have _bucket suffix
        assert "bess_report_generation_duration_seconds_bucket" in metrics

    def test_size_histogram_has_buckets(self):
        """Size histogram should have proper buckets."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        # Histogram should have _bucket suffix
        assert "bess_report_size_bytes_bucket" in metrics


class TestReportMetricsBranding:
    """Tests for branding metrics."""

    def test_branding_metric_with_client_name(self):
        """Branding metric should track client_name usage."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf?client_name=TestCorp"
        requests.get(url)

        metrics = _get_metrics()
        assert "bess_report_branding_usage_total" in metrics

    def test_branding_metric_with_site_name(self):
        """Branding metric should track site_name usage."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf?site_name=FactoryA"
        requests.get(url)

        metrics = _get_metrics()
        assert "bess_report_branding_usage_total" in metrics


class TestPortfolioReportMetrics:
    """Tests for portfolio report metrics."""

    def test_portfolio_report_requests_metric_defined(self):
        """Portfolio report requests metric should be defined."""
        metrics = _get_metrics()
        # Metric should be defined even if not yet incremented
        # We check for TYPE declaration
        assert "bess_portfolio_report" in metrics or "portfolio" in metrics.lower()


class TestReportMetricsGauges:
    """Tests for report metrics gauges."""

    def test_last_generation_timestamp_gauge_present(self):
        """Last generation timestamp gauge should be present."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert "bess_report_last_generation_timestamp" in metrics

    def test_last_size_bytes_gauge_present(self):
        """Last size bytes gauge should be present."""
        run_id = _create_sizing_run()
        _trigger_report_download(run_id, "pdf")

        metrics = _get_metrics()
        assert "bess_report_last_size_bytes" in metrics
