"""
Contract tests for v1.3.0 metadata observability metrics.

Tests verify:
- Run metadata PATCH metrics
- Run list filter metrics (tag, q, sort)
- Job metadata PATCH metrics
- Metrics format (HELP and TYPE lines)
"""
import time

import pytest
import requests

from ._api import post_json, get_json, patch_json, load_smoke_payload


# API paths
SIZING_PATH = "/sizing"
RUNS_PATH = "/runs"
JOBS_PATH = "/api/bess-dispatch/jobs"
METRICS_PATH = "/metrics"
BASE_URL = "http://localhost:8031"


def get_metrics():
    """Fetch /metrics endpoint content."""
    response = requests.get(f"{BASE_URL}{METRICS_PATH}")
    assert response.status_code == 200
    return response.text


def create_sizing_run():
    """Create a sizing run and return the run_id."""
    payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
    response = post_json(SIZING_PATH, payload)
    return response["cache_info"]["run_id"]


def create_job_sync():
    """Create a sizing job (sync) and return the job_id."""
    payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
    batch_request = {
        "items": [
            {"item_id": "test-item-1", "request": payload}
        ],
        "wait": True,
    }
    response = post_json(f"{JOBS_PATH}/sizing-batch", batch_request)
    return response["job_id"]


class TestRunMetadataPatchMetrics:
    """Test run metadata PATCH metrics."""

    def test_patch_metrics_present_after_request(self):
        """Verify run metadata PATCH metrics appear after a PATCH request."""
        run_id = create_sizing_run()

        # PATCH with label and tags
        patch_json(f"{RUNS_PATH}/{run_id}", {
            "label": "Test Label",
            "tags": ["tag1", "tag2"]
        })

        metrics = get_metrics()
        assert "bess_run_metadata_patch_total" in metrics

    def test_patch_metrics_include_has_label(self):
        """Verify PATCH metrics include has_label dimension."""
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"label": "Test"})

        metrics = get_metrics()
        assert 'has_label="true"' in metrics

    def test_patch_metrics_include_has_tags(self):
        """Verify PATCH metrics include has_tags dimension."""
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["a", "b"]})

        metrics = get_metrics()
        assert 'has_tags="true"' in metrics

    def test_patch_metrics_include_has_notes(self):
        """Verify PATCH metrics include has_notes dimension."""
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"notes": "Test notes"})

        metrics = get_metrics()
        assert 'has_notes="true"' in metrics

    def test_tags_count_histogram_present(self):
        """Verify tags count histogram is recorded."""
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["a", "b", "c", "d", "e"]})

        metrics = get_metrics()
        assert "bess_run_metadata_tags_count" in metrics


class TestRunListFilterMetrics:
    """Test run list filter metrics."""

    def test_tag_filter_metric_present(self):
        """Verify tag filter metric is recorded."""
        # Create run with tag
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["testtag"]})

        # Query with tag filter
        requests.get(f"{BASE_URL}{RUNS_PATH}?tag=testtag")

        metrics = get_metrics()
        assert "bess_run_list_tag_filter_total" in metrics

    def test_search_metric_present(self):
        """Verify search (q) metric is recorded."""
        # Query with search
        requests.get(f"{BASE_URL}{RUNS_PATH}?q=testsearch")

        metrics = get_metrics()
        assert "bess_run_list_search_total" in metrics

    def test_sort_metric_present(self):
        """Verify sort metric is recorded."""
        # Query with sort
        requests.get(f"{BASE_URL}{RUNS_PATH}?sort=created_at_asc")

        metrics = get_metrics()
        assert "bess_run_list_sort_total" in metrics

    def test_sort_metric_has_sort_order_label(self):
        """Verify sort metric has sort_order label."""
        requests.get(f"{BASE_URL}{RUNS_PATH}?sort=updated_at_desc")

        metrics = get_metrics()
        assert 'sort_order="updated_at_desc"' in metrics


class TestJobMetadataPatchMetrics:
    """Test job metadata PATCH metrics."""

    def test_patch_metrics_present_after_request(self):
        """Verify job metadata PATCH metrics appear after a PATCH request."""
        job_id = create_job_sync()

        # PATCH with label
        patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Test Label"})

        metrics = get_metrics()
        assert "bess_job_metadata_patch_total" in metrics

    def test_patch_metrics_include_has_label(self):
        """Verify job PATCH metrics include has_label dimension."""
        job_id = create_job_sync()
        patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Test"})

        metrics = get_metrics()
        assert 'has_label="true"' in metrics

    def test_job_tags_count_histogram_present(self):
        """Verify job tags count histogram is recorded."""
        job_id = create_job_sync()
        patch_json(f"{JOBS_PATH}/{job_id}", {"tags": ["a", "b", "c"]})

        metrics = get_metrics()
        assert "bess_job_metadata_tags_count" in metrics


class TestMetadataMetricsFormat:
    """Test metrics format."""

    def test_run_patch_metric_has_help_line(self):
        """Verify run PATCH metric has HELP line."""
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"label": "Test"})

        metrics = get_metrics()
        assert "# HELP bess_run_metadata_patch_total" in metrics

    def test_run_patch_metric_has_type_line(self):
        """Verify run PATCH metric has TYPE line."""
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"label": "Test"})

        metrics = get_metrics()
        assert "# TYPE bess_run_metadata_patch_total counter" in metrics

    def test_job_patch_metric_has_help_line(self):
        """Verify job PATCH metric has HELP line."""
        job_id = create_job_sync()
        patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Test"})

        metrics = get_metrics()
        assert "# HELP bess_job_metadata_patch_total" in metrics

    def test_job_patch_metric_has_type_line(self):
        """Verify job PATCH metric has TYPE line."""
        job_id = create_job_sync()
        patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Test"})

        metrics = get_metrics()
        assert "# TYPE bess_job_metadata_patch_total counter" in metrics

    def test_tags_count_histogram_has_type_line(self):
        """Verify tags count histogram has TYPE line."""
        run_id = create_sizing_run()
        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["a"]})

        metrics = get_metrics()
        assert "# TYPE bess_run_metadata_tags_count histogram" in metrics
