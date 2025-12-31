"""
Contract tests for repro bundle and debug events metrics (v1.8.0).

Tests verify:
- Repro download counters are present in /metrics
- Debug events counters are present after sizing requests
- Debug events histograms are present after sizing requests
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def get_metrics():
    """Get Prometheus metrics from /metrics endpoint."""
    resp = requests.get(f"{BASE_URL}/metrics", timeout=30)
    return resp.text


def create_sizing_request():
    """Create a sizing request to generate debug events."""
    n_hours = 24
    request = {
        "pv_generation_kw": [50.0] * n_hours,
        "load_kw": [30.0] * n_hours,
        "interval_minutes": 60,
        "battery_power_kw": 50.0,
        "battery_energy_kwh": 100.0,
        "mode": "pv_surplus",
        "prices": {
            "import_price_pln_kwh": 0.8,
            "export_price_pln_kwh": 0.4,
        },
    }
    response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Sizing failed: {response.text}"
    return response.json()


def get_run_id():
    """Get a run_id by creating a sizing request."""
    sizing_result = create_sizing_request()
    cache_info = sizing_result.get("cache_info", {})
    run_id = cache_info.get("run_id")
    assert run_id is not None, "run_id not found in sizing response"
    return run_id


class TestReproMetricsPresence:
    """Contract tests for repro bundle metrics presence."""

    def test_repro_run_download_metric_present_after_download(self):
        """Verify repro run download counter is present after download."""
        run_id = get_run_id()

        # Download repro.zip
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        assert response.status_code == 200

        metrics = get_metrics()
        assert "bess_repro_run_downloads_total" in metrics

    def test_repro_run_download_success_counter(self):
        """Verify repro run download success counter is present."""
        run_id = get_run_id()

        # Download repro.zip
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        assert response.status_code == 200

        metrics = get_metrics()
        assert 'bess_repro_run_downloads_total{status="success"}' in metrics

    def test_repro_run_download_not_found_counter(self):
        """Verify repro run download not_found counter is present."""
        # Request non-existent run
        response = requests.get(f"{BASE_URL}/runs/nonexistent-run-id/repro.zip", timeout=30)
        assert response.status_code == 404

        metrics = get_metrics()
        assert 'bess_repro_run_downloads_total{status="not_found"}' in metrics


class TestDebugEventsMetricsPresence:
    """Contract tests for debug events metrics presence."""

    def test_debug_events_export_limited_counter_present(self):
        """Verify export limited counter is present after sizing."""
        create_sizing_request()
        metrics = get_metrics()
        # May or may not be incremented, but HELP/TYPE should be present
        assert "bess_debug_events_export_limited_total" in metrics

    def test_debug_events_import_limited_counter_present(self):
        """Verify import limited counter is present after sizing."""
        create_sizing_request()
        metrics = get_metrics()
        assert "bess_debug_events_import_limited_total" in metrics

    def test_debug_events_pv_curtail_counter_present(self):
        """Verify PV curtail counter is present after sizing."""
        create_sizing_request()
        metrics = get_metrics()
        assert "bess_debug_events_pv_curtail_total" in metrics

    def test_debug_events_unserved_load_counter_present(self):
        """Verify unserved load counter is present after sizing."""
        create_sizing_request()
        metrics = get_metrics()
        assert "bess_debug_events_unserved_load_total" in metrics


class TestDebugEventsHistogramsPresence:
    """Contract tests for debug events histogram presence."""

    def test_debug_events_export_limited_mwh_histogram_present(self):
        """Verify export limited MWh histogram is present."""
        create_sizing_request()
        metrics = get_metrics()
        assert "bess_debug_events_export_limited_mwh" in metrics

    def test_debug_events_import_limited_mwh_histogram_present(self):
        """Verify import limited MWh histogram is present."""
        create_sizing_request()
        metrics = get_metrics()
        assert "bess_debug_events_import_limited_mwh" in metrics

    def test_debug_events_pv_curtail_mwh_histogram_present(self):
        """Verify PV curtail MWh histogram is present."""
        create_sizing_request()
        metrics = get_metrics()
        assert "bess_debug_events_pv_curtail_mwh" in metrics

    def test_debug_events_unserved_load_kwh_histogram_present(self):
        """Verify unserved load kWh histogram is present."""
        create_sizing_request()
        metrics = get_metrics()
        assert "bess_debug_events_unserved_load_kwh" in metrics


class TestMetricsFormat:
    """Contract tests for Prometheus metrics format."""

    def test_repro_run_downloads_has_help_and_type(self):
        """Verify repro run downloads has HELP and TYPE lines."""
        run_id = get_run_id()
        requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)

        metrics = get_metrics()
        assert "# HELP bess_repro_run_downloads_total" in metrics
        assert "# TYPE bess_repro_run_downloads_total counter" in metrics

    def test_debug_events_export_limited_has_help_and_type(self):
        """Verify export limited counter has HELP and TYPE lines."""
        create_sizing_request()
        metrics = get_metrics()
        assert "# HELP bess_debug_events_export_limited_total" in metrics
        assert "# TYPE bess_debug_events_export_limited_total counter" in metrics

    def test_debug_events_export_limited_mwh_has_help_and_type(self):
        """Verify export limited MWh histogram has HELP and TYPE lines."""
        create_sizing_request()
        metrics = get_metrics()
        assert "# HELP bess_debug_events_export_limited_mwh" in metrics
        assert "# TYPE bess_debug_events_export_limited_mwh histogram" in metrics
