"""
Contract tests for v1.0.0 RunStore Prometheus metrics.

Tests verify:
- Metrics are exposed after run store operations
- Counter and histogram metrics have correct format
- Labels are correctly applied

Run with: pytest tests/contract/test_runstore_metrics_contract.py -v
"""
import pytest
import requests
from ._api import post_json, get_json


SIZING_ENDPOINT = "/sizing"
RUNS_ENDPOINT = "/runs"
METRICS_URL = "http://localhost:8031/metrics"
CACHE_CLEAR_URL = "http://localhost:8031/cache"


def make_sizing_request(load_variation: int = 0):
    """Create sizing request with optional load variation for unique requests."""
    return {
        "load_kw": [100 + load_variation, 120, 110, 90],
        "pv_generation_kw": [50, 70, 80, 60],
        "energy_price_pln_kwh": 0.8,
    }


def get_metrics():
    """Fetch Prometheus metrics from /metrics endpoint."""
    r = requests.get(METRICS_URL, timeout=30)
    return r.text


class TestRunstoreSavesMetrics:
    """Tests for bess_runstore_saves_total counter."""

    def test_saves_metric_present_after_sizing(self):
        """Verify saves metric appears after sizing request."""
        # Clear cache to ensure we get a cache miss
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request(load_variation=5001)
        post_json(SIZING_ENDPOINT, req)

        metrics = get_metrics()

        assert "bess_runstore_saves_total" in metrics

    def test_saves_metric_has_endpoint_label(self):
        """Verify saves metric has endpoint label."""
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)

        metrics = get_metrics()

        assert 'endpoint="sizing"' in metrics

    def test_saves_metric_has_cache_hit_label(self):
        """Verify saves metric has cache_hit label."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request(load_variation=5002)
        # First request - cache miss
        post_json(SIZING_ENDPOINT, req)
        # Second request - cache hit
        post_json(SIZING_ENDPOINT, req)

        metrics = get_metrics()

        # Should have both cache_hit values
        assert 'cache_hit="false"' in metrics
        assert 'cache_hit="true"' in metrics


class TestRunstoreGetsMetrics:
    """Tests for bess_runstore_gets_total counter."""

    def test_gets_metric_present_after_get_run(self):
        """Verify gets metric appears after GET /runs/{run_id}."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        # Get the run
        get_json(f"{RUNS_ENDPOINT}/{run_id}")

        metrics = get_metrics()

        assert "bess_runstore_gets_total" in metrics

    def test_gets_metric_has_found_label(self):
        """Verify gets metric has found label."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        # Get existing run
        get_json(f"{RUNS_ENDPOINT}/{run_id}")

        # Try to get non-existent run
        try:
            requests.get(
                f"http://localhost:8031{RUNS_ENDPOINT}/00000000-0000-0000-0000-000000000000"
            )
        except Exception:
            pass

        metrics = get_metrics()

        assert 'found="true"' in metrics


class TestRunstoreListMetrics:
    """Tests for bess_runstore_list_requests_total counter."""

    def test_list_metric_present_after_list_runs(self):
        """Verify list metric appears after GET /runs."""
        get_json(RUNS_ENDPOINT)

        metrics = get_metrics()

        assert "bess_runstore_list_requests_total" in metrics

    def test_list_metric_has_has_filters_label(self):
        """Verify list metric has has_filters label."""
        # List without filters
        get_json(RUNS_ENDPOINT)
        # List with filters
        get_json(f"{RUNS_ENDPOINT}?endpoint=sizing")

        metrics = get_metrics()

        assert 'has_filters="false"' in metrics
        assert 'has_filters="true"' in metrics


class TestRunstorePruneMetrics:
    """Tests for bess_runstore_prune_total counter."""

    def test_prune_metric_present_after_prune(self):
        """Verify prune metric appears after POST /runs:prune."""
        requests.post(
            "http://localhost:8031/runs:prune",
            json={"retention_days": 365},
            timeout=30
        )

        metrics = get_metrics()

        assert "bess_runstore_prune_total" in metrics

    def test_deleted_count_histogram_present(self):
        """Verify deleted count histogram appears after prune."""
        requests.post(
            "http://localhost:8031/runs:prune",
            json={"retention_days": 365},
            timeout=30
        )

        metrics = get_metrics()

        assert "bess_runstore_deleted_count" in metrics

    def test_retention_days_histogram_present(self):
        """Verify retention days histogram appears after prune."""
        requests.post(
            "http://localhost:8031/runs:prune",
            json={"retention_days": 30},
            timeout=30
        )

        metrics = get_metrics()

        assert "bess_runstore_retention_days" in metrics


class TestRunstoreCompareMetrics:
    """Tests for bess_runstore_compare_total counter."""

    def test_compare_metric_present_after_compare(self):
        """Verify compare metric appears after POST /runs:compare."""
        # Create two runs to compare
        requests.delete(CACHE_CLEAR_URL)
        req1 = make_sizing_request(load_variation=6001)
        resp1 = post_json(SIZING_ENDPOINT, req1)
        run_id1 = resp1["cache_info"]["run_id"]

        req2 = make_sizing_request(load_variation=6002)
        resp2 = post_json(SIZING_ENDPOINT, req2)
        run_id2 = resp2["cache_info"]["run_id"]

        # Compare them
        requests.post(
            "http://localhost:8031/runs:compare",
            json={"run_id_a": run_id1, "run_id_b": run_id2},
            timeout=30
        )

        metrics = get_metrics()

        assert "bess_runstore_compare_total" in metrics

    def test_compare_metric_has_variant_changed_label(self):
        """Verify compare metric has variant_changed label."""
        requests.delete(CACHE_CLEAR_URL)
        req1 = make_sizing_request(load_variation=6003)
        resp1 = post_json(SIZING_ENDPOINT, req1)
        run_id1 = resp1["cache_info"]["run_id"]

        req2 = make_sizing_request(load_variation=6004)
        resp2 = post_json(SIZING_ENDPOINT, req2)
        run_id2 = resp2["cache_info"]["run_id"]

        requests.post(
            "http://localhost:8031/runs:compare",
            json={"run_id_a": run_id1, "run_id_b": run_id2},
            timeout=30
        )

        metrics = get_metrics()

        # Should have variant_changed label (true or false)
        assert 'variant_changed="true"' in metrics or 'variant_changed="false"' in metrics


class TestRunstoreExportMetrics:
    """Tests for bess_runstore_export_total counter."""

    def test_export_json_metric_present(self):
        """Verify export metric appears after JSON export."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        # Export as JSON
        requests.get(f"http://localhost:8031{RUNS_ENDPOINT}/{run_id}/export/json")

        metrics = get_metrics()

        assert "bess_runstore_export_total" in metrics
        assert 'format="json"' in metrics

    def test_export_csv_metric_present(self):
        """Verify export metric appears after CSV export."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        # Export as CSV
        requests.get(f"http://localhost:8031{RUNS_ENDPOINT}/{run_id}/export/csv")

        metrics = get_metrics()

        assert 'format="csv"' in metrics


class TestMetricsFormat:
    """Tests for Prometheus metrics format."""

    def test_metrics_have_help_line(self):
        """Verify metrics have HELP line."""
        # Trigger a few operations to ensure metrics exist
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)
        get_json(RUNS_ENDPOINT)

        metrics = get_metrics()

        assert "# HELP bess_runstore_saves_total" in metrics

    def test_metrics_have_type_line(self):
        """Verify metrics have TYPE line."""
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)

        metrics = get_metrics()

        assert "# TYPE bess_runstore_saves_total counter" in metrics
