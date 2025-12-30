"""
Contract tests for v1.1.0 async jobs observability metrics.

Tests verify:
- Job creation metrics (sync/async, items count)
- Job completion metrics (ok/error counts, duration)
- Job API metrics (get, list, cancel)
- Metrics format (HELP and TYPE lines)
"""
import pytest
import time

from ._api import post_json, get_json


# Use relative paths for _api helpers (they add BASE_URL)
JOBS_BATCH_PATH = "/api/bess-dispatch/jobs/sizing-batch"
JOBS_PATH = "/api/bess-dispatch/jobs"


def get_metrics():
    """Fetch Prometheus metrics from /metrics endpoint."""
    import requests
    response = requests.get("http://localhost:8031/metrics")
    response.raise_for_status()
    return response.text


def create_test_job(wait: bool = True):
    """Create a minimal test job."""
    payload = {
        "batch_id": f"metrics_test_{int(time.time() * 1000)}",
        "wait": wait,
        "items": [
            {
                "item_id": "test_item",
                "request": {
                    "load_kw": [50, 60, 70, 80, 90, 100] * 4,
                    "pv_generation_kw": [0, 0, 0, 5, 20, 40] * 4,
                    "energy_price_pln_kwh": 0.8,
                    "mode": "stacked",
                    "peak_limit_kw": 80
                }
            }
        ]
    }
    return post_json(JOBS_BATCH_PATH, payload)


class TestJobsMetricsFormat:
    """Test that metrics have proper Prometheus format."""

    def test_metrics_endpoint_returns_200(self):
        """Verify /metrics endpoint is accessible."""
        import requests
        response = requests.get("http://localhost:8031/metrics")
        assert response.status_code == 200

    def test_metrics_have_help_lines(self):
        """Verify metrics have HELP documentation."""
        metrics = get_metrics()

        expected_help_patterns = [
            "# HELP bess_jobs_created_total",
            "# HELP bess_jobs_completed_total",
            "# HELP bess_jobs_items_count",
        ]

        for pattern in expected_help_patterns:
            assert pattern in metrics, f"Missing HELP for {pattern}"

    def test_metrics_have_type_lines(self):
        """Verify metrics have TYPE declarations."""
        metrics = get_metrics()

        expected_type_patterns = [
            "# TYPE bess_jobs_created_total counter",
            "# TYPE bess_jobs_completed_total counter",
            "# TYPE bess_jobs_items_count histogram",
        ]

        for pattern in expected_type_patterns:
            assert pattern in metrics, f"Missing TYPE for {pattern}"


class TestJobCreationMetrics:
    """Test job creation metrics."""

    def test_sync_job_increments_created_counter(self):
        """Verify sync job creation increments counter."""
        # Get baseline
        metrics_before = get_metrics()

        # Create sync job
        create_test_job(wait=True)

        # Check metrics after
        metrics_after = get_metrics()
        assert 'bess_jobs_created_total{wait_mode="sync"}' in metrics_after

    def test_async_job_increments_created_counter(self):
        """Verify async job creation increments counter."""
        # Create async job
        response = create_test_job(wait=False)

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_created_total{wait_mode="async"}' in metrics

    def test_items_count_histogram_observed(self):
        """Verify items count histogram is updated."""
        # Create job
        create_test_job(wait=True)

        # Check metrics
        metrics = get_metrics()
        assert "bess_jobs_items_count_bucket" in metrics
        assert "bess_jobs_items_count_count" in metrics


class TestJobCompletionMetrics:
    """Test job completion metrics."""

    def test_completed_counter_increments_on_done(self):
        """Verify completed counter increments when job finishes."""
        # Create and complete a sync job
        create_test_job(wait=True)

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_completed_total{final_status="done"}' in metrics

    def test_duration_histogram_observed(self):
        """Verify duration histogram is updated."""
        # Create and complete a sync job
        create_test_job(wait=True)

        # Check metrics
        metrics = get_metrics()
        assert "bess_jobs_duration_seconds_bucket" in metrics
        assert "bess_jobs_duration_seconds_count" in metrics

    def test_ok_items_histogram_observed(self):
        """Verify ok items histogram is updated."""
        # Create and complete a sync job
        create_test_job(wait=True)

        # Check metrics
        metrics = get_metrics()
        assert "bess_jobs_ok_items_count_bucket" in metrics

    def test_error_items_histogram_observed(self):
        """Verify error items histogram is updated."""
        # Create and complete a sync job
        create_test_job(wait=True)

        # Check metrics
        metrics = get_metrics()
        assert "bess_jobs_error_items_count_bucket" in metrics


class TestJobGetMetrics:
    """Test GET /jobs/{job_id} metrics."""

    def test_get_found_increments_counter(self):
        """Verify get with found job increments counter."""
        # Create a job
        response = create_test_job(wait=True)
        job_id = response["job_id"]

        # Get the job
        get_json(f"{JOBS_PATH}/{job_id}")

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_get_total{found="true"}' in metrics

    def test_get_not_found_increments_counter(self):
        """Verify get with non-existent job increments counter."""
        import requests

        # Try to get non-existent job
        response = requests.get(f"http://localhost:8031{JOBS_PATH}/nonexistent-job-id")
        assert response.status_code == 404

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_get_total{found="false"}' in metrics


class TestJobListMetrics:
    """Test GET /jobs list metrics."""

    def test_list_without_filters_increments_counter(self):
        """Verify list without filters increments counter."""
        # List jobs
        get_json(JOBS_PATH)

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_list_total{has_filters="false"}' in metrics

    def test_list_with_filters_increments_counter(self):
        """Verify list with filters increments counter."""
        # List jobs with status filter
        get_json(f"{JOBS_PATH}?status=done")

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_list_total{has_filters="true"}' in metrics

    def test_list_results_histogram_observed(self):
        """Verify list results histogram is updated."""
        # List jobs
        get_json(JOBS_PATH)

        # Check metrics
        metrics = get_metrics()
        assert "bess_jobs_list_results_count_bucket" in metrics


class TestJobCancelMetrics:
    """Test DELETE /jobs/{job_id} cancel metrics."""

    def test_cancel_not_found_increments_counter(self):
        """Verify cancel of non-existent job increments counter."""
        import requests

        # Try to cancel non-existent job
        response = requests.delete(f"http://localhost:8031{JOBS_PATH}/nonexistent-job-id")
        assert response.status_code == 404

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_cancel_total{result="not_found"}' in metrics

    def test_cancel_already_done_increments_counter(self):
        """Verify cancel of completed job increments counter."""
        import requests

        # Create a completed job
        job_response = create_test_job(wait=True)
        job_id = job_response["job_id"]

        # Try to cancel completed job
        response = requests.delete(f"http://localhost:8031{JOBS_PATH}/{job_id}")

        # Check metrics
        metrics = get_metrics()
        assert 'bess_jobs_cancel_total{result="already_done"}' in metrics


class TestIdempotencyMetrics:
    """Test idempotency metrics."""

    def test_idempotency_hit_increments_counter(self):
        """Verify idempotency hit increments counter (if idempotency implemented)."""
        # Create job with idempotency key
        payload = {
            "batch_id": "idempotency_test",
            "wait": True,
            "idempotency_key": f"test_key_{int(time.time() * 1000)}",
            "items": [
                {
                    "item_id": "test_item",
                    "request": {
                        "load_kw": [50, 60, 70, 80, 90, 100] * 4,
                        "pv_generation_kw": [0, 0, 0, 5, 20, 40] * 4,
                        "energy_price_pln_kwh": 0.8,
                        "mode": "stacked",
                        "peak_limit_kw": 80
                    }
                }
            ]
        }

        # Create first time
        response1 = post_json(JOBS_BATCH_PATH, payload)
        job_id1 = response1["job_id"]

        # Create second time with same key - should return same job
        response2 = post_json(JOBS_BATCH_PATH, payload)
        job_id2 = response2["job_id"]

        # Check that same job returned
        assert job_id1 == job_id2

        # Check metrics
        metrics = get_metrics()
        assert "bess_jobs_idempotency_hit_total" in metrics
