"""
Contract tests for v1.2.0 job retention observability metrics.

Tests verify:
- Prune/vacuum/stats/retention metrics are recorded
- SSE connection metrics are recorded
- Job export metrics are recorded
- Metrics have proper HELP and TYPE lines
"""
import time

import pytest
import requests

from ._api import post_json


# API paths
JOBS_BATCH_PATH = "/api/bess-dispatch/jobs/sizing-batch"
JOBS_RETENTION_PATH = "/api/bess-dispatch/jobs/retention"
JOBS_PRUNE_PATH = "/api/bess-dispatch/jobs:prune"
JOBS_VACUUM_PATH = "/api/bess-dispatch/jobs:vacuum"
JOBS_STATS_PATH = "/api/bess-dispatch/jobs/stats"
METRICS_PATH = "/metrics"
BASE_URL = "http://localhost:8031"


def create_completed_job():
    """Create a completed job for testing."""
    payload = {
        "batch_id": f"metrics_test_{int(time.time() * 1000)}",
        "wait": True,
        "items": [
            {
                "item_id": "test_item",
                "request": {
                    "load_kw": [50, 60, 70, 80, 90, 100] * 4,
                    "pv_generation_kw": [0, 0, 0, 5, 20, 40] * 4,
                    "energy_price_pln_kwh": 0.8,
                    "mode": "stacked",
                    "peak_limit_kw": 80,
                },
            }
        ],
    }
    return post_json(JOBS_BATCH_PATH, payload)


def get_metrics():
    """Fetch Prometheus metrics."""
    response = requests.get(f"{BASE_URL}{METRICS_PATH}")
    assert response.status_code == 200
    return response.text


class TestRetentionMetricsFormat:
    """Test metrics format and HELP/TYPE lines."""

    def test_metrics_endpoint_returns_200(self):
        """Verify metrics endpoint works."""
        response = requests.get(f"{BASE_URL}{METRICS_PATH}")
        assert response.status_code == 200

    def test_metrics_have_help_lines(self):
        """Verify HELP lines are present for new metrics."""
        # Trigger some metrics first
        requests.get(f"{BASE_URL}{JOBS_RETENTION_PATH}")
        requests.post(f"{BASE_URL}{JOBS_PRUNE_PATH}", json={})
        requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")
        requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")

        metrics = get_metrics()

        # Check for HELP lines
        assert "# HELP bess_jobs_retention_config_total" in metrics
        assert "# HELP bess_jobs_prune_total" in metrics
        assert "# HELP bess_jobs_vacuum_total" in metrics
        assert "# HELP bess_jobs_stats_total" in metrics

    def test_metrics_have_type_lines(self):
        """Verify TYPE lines are present for new metrics."""
        metrics = get_metrics()

        # Check for TYPE lines
        assert "# TYPE bess_jobs_retention_config_total counter" in metrics
        assert "# TYPE bess_jobs_prune_total counter" in metrics
        assert "# TYPE bess_jobs_vacuum_total counter" in metrics
        assert "# TYPE bess_jobs_stats_total counter" in metrics


class TestRetentionConfigMetrics:
    """Test GET /jobs/retention metrics."""

    def test_retention_config_counter_increments(self):
        """Verify retention config counter increments."""
        # Get initial count
        metrics1 = get_metrics()
        initial_count = metrics1.count("bess_jobs_retention_config_total")

        # Make request
        requests.get(f"{BASE_URL}{JOBS_RETENTION_PATH}")

        # Verify counter exists in metrics
        metrics2 = get_metrics()
        assert "bess_jobs_retention_config_total" in metrics2


class TestPruneMetrics:
    """Test POST /jobs:prune metrics."""

    def test_prune_counter_increments(self):
        """Verify prune counter increments."""
        requests.post(f"{BASE_URL}{JOBS_PRUNE_PATH}", json={})

        metrics = get_metrics()
        assert "bess_jobs_prune_total" in metrics

    def test_prune_retention_days_histogram(self):
        """Verify retention days histogram is populated."""
        requests.post(f"{BASE_URL}{JOBS_PRUNE_PATH}", json={"retention_days": 30})

        metrics = get_metrics()
        assert "bess_jobs_prune_retention_days" in metrics


class TestVacuumMetrics:
    """Test POST /jobs:vacuum metrics."""

    def test_vacuum_counter_increments(self):
        """Verify vacuum counter increments."""
        requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")

        metrics = get_metrics()
        assert "bess_jobs_vacuum_total" in metrics

    def test_vacuum_freed_bytes_histogram(self):
        """Verify freed bytes histogram is populated."""
        requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")

        metrics = get_metrics()
        assert "bess_jobs_vacuum_freed_bytes" in metrics


class TestStatsMetrics:
    """Test GET /jobs/stats metrics."""

    def test_stats_counter_increments(self):
        """Verify stats counter increments."""
        # Create a job first to ensure database exists
        create_completed_job()

        requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")

        metrics = get_metrics()
        assert "bess_jobs_stats_total" in metrics


class TestSSEMetrics:
    """Test SSE connection metrics."""

    def test_sse_connection_counter_increments(self):
        """Verify SSE connection counter increments."""
        job = create_completed_job()

        # Connect to SSE endpoint
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{job['job_id']}/events"
        )
        assert response.status_code == 200

        metrics = get_metrics()
        assert "bess_jobs_sse_connections_total" in metrics

    def test_sse_events_sent_counter(self):
        """Verify SSE events sent counter increments."""
        job = create_completed_job()

        # Connect to SSE endpoint (completed job sends immediate done event)
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{job['job_id']}/events"
        )
        assert response.status_code == 200

        metrics = get_metrics()
        assert "bess_jobs_sse_events_sent_total" in metrics


class TestExportMetrics:
    """Test job export metrics."""

    def test_json_export_counter(self):
        """Verify JSON export counter increments."""
        job = create_completed_job()

        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{job['job_id']}/export/json"
        )
        assert response.status_code == 200

        metrics = get_metrics()
        assert "bess_jobs_export_total" in metrics
        assert 'format="json"' in metrics

    def test_csv_export_counter(self):
        """Verify CSV export counter increments."""
        job = create_completed_job()

        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{job['job_id']}/export/csv"
        )
        assert response.status_code == 200

        metrics = get_metrics()
        assert 'format="csv"' in metrics

    def test_zip_export_counter(self):
        """Verify ZIP export counter increments."""
        job = create_completed_job()

        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{job['job_id']}/export/zip"
        )
        assert response.status_code == 200

        metrics = get_metrics()
        assert 'format="zip"' in metrics
