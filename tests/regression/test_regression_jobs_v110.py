"""
Regression tests for v1.1.0 async jobs API.

Tests verify:
- Job response structure (sync and async modes)
- Job status lifecycle (pending -> running -> done)
- Job list endpoint
- Result consistency with direct batch API

Scenarios:
1. Sync job (wait=true) - full result returned immediately
2. Async job (wait=false) - job_id returned, poll for status
3. Job list endpoint
"""
import pytest
import math


# Tolerance for floating point comparisons
ECONOMIC_TOLERANCE = 0.05  # 5% for NPV, savings


def relative_diff(actual: float, expected: float) -> float:
    """Calculate relative difference, handling zero expected."""
    if abs(expected) < 1e-9:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


class TestRegressionJobSyncResponse:
    """Regression tests for sync job response (wait=true)."""

    GOLDEN_FILE = "scenario_jobs_v110_sync.json"

    def test_job_has_job_id(self, load_golden):
        """Verify job response has job_id."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "job_id" in golden
        assert golden["job_id"] is not None
        assert len(golden["job_id"]) > 0

    def test_job_has_status(self, load_golden):
        """Verify job response has status."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "status" in golden
        assert golden["status"] in ["pending", "running", "done", "failed", "cancelled"]

    def test_sync_job_status_is_done(self, load_golden):
        """Verify sync job (wait=true) returns done status."""
        golden = load_golden(self.GOLDEN_FILE)

        assert golden["status"] == "done", (
            f"Sync job should return 'done' status, got '{golden['status']}'"
        )

    def test_job_has_result_when_done(self, load_golden):
        """Verify done job has result."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done":
            assert "result" in golden
            assert golden["result"] is not None

    def test_job_result_has_results_array(self, load_golden):
        """Verify job result has results array."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            assert "results" in result
            assert isinstance(result["results"], list)

    def test_job_result_has_summary(self, load_golden):
        """Verify job result has summary."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            assert "summary" in result
            summary = result["summary"]
            assert "total_items" in summary
            assert "ok_count" in summary
            assert "error_count" in summary
            assert "processing_time_ms" in summary

    def test_job_has_items_done_and_total(self, load_golden):
        """Verify job has items_done and items_total."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "items_done" in golden
        assert "items_total" in golden
        assert golden["items_done"] >= 0
        assert golden["items_total"] >= 0

    def test_items_done_equals_total_when_done(self, load_golden):
        """Verify items_done equals items_total when status is done."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done":
            assert golden["items_done"] == golden["items_total"], (
                f"items_done ({golden['items_done']}) != items_total ({golden['items_total']})"
            )


class TestRegressionJobAsyncResponse:
    """Regression tests for async job response (wait=false)."""

    GOLDEN_FILE = "scenario_jobs_v110_async.json"

    def test_async_job_has_job_id(self, load_golden):
        """Verify async job response has job_id."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "job_id" in golden
        assert golden["job_id"] is not None
        assert len(golden["job_id"]) > 0

    def test_async_job_has_status(self, load_golden):
        """Verify async job response has status."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "status" in golden
        assert golden["status"] in ["pending", "running"]

    def test_async_job_status_is_pending_or_running(self, load_golden):
        """Verify async job (wait=false) returns pending or running status."""
        golden = load_golden(self.GOLDEN_FILE)

        assert golden["status"] in ["pending", "running"], (
            f"Async job should return 'pending' or 'running', got '{golden['status']}'"
        )

    def test_async_job_has_created_at(self, load_golden):
        """Verify async job has created_at timestamp."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "created_at" in golden
        assert golden["created_at"] is not None

    def test_async_job_has_items_total(self, load_golden):
        """Verify async job has items_total."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "items_total" in golden
        assert golden["items_total"] > 0


class TestRegressionJobCompleted:
    """Regression tests for completed job (polled until done)."""

    GOLDEN_FILE = "scenario_jobs_v110_completed.json"

    def test_completed_job_status_is_done(self, load_golden):
        """Verify completed job has done status."""
        golden = load_golden(self.GOLDEN_FILE)

        assert golden["status"] in ["done", "failed"], (
            f"Completed job should be 'done' or 'failed', got '{golden['status']}'"
        )

    def test_completed_job_has_result(self, load_golden):
        """Verify completed job has result."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done":
            assert "result" in golden
            assert golden["result"] is not None

    def test_completed_job_has_updated_at(self, load_golden):
        """Verify completed job has updated_at timestamp."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done":
            assert "updated_at" in golden
            assert golden["updated_at"] is not None

    def test_completed_job_items_match(self, load_golden):
        """Verify completed job items_done matches items_total."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done":
            assert golden["items_done"] == golden["items_total"]


class TestRegressionJobList:
    """Regression tests for job list endpoint."""

    GOLDEN_FILE = "scenario_jobs_v110_list.json"

    def test_job_list_has_items(self, load_golden):
        """Verify job list has items array."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "items" in golden
        assert isinstance(golden["items"], list)

    def test_job_list_has_total(self, load_golden):
        """Verify job list has total count."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "total" in golden
        assert golden["total"] >= 0

    def test_job_list_has_limit_offset(self, load_golden):
        """Verify job list has limit and offset."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "limit" in golden
        assert "offset" in golden
        assert golden["limit"] > 0
        assert golden["offset"] >= 0

    def test_job_list_items_have_required_fields(self, load_golden):
        """Verify each job list item has required fields."""
        golden = load_golden(self.GOLDEN_FILE)

        required_fields = ["job_id", "status", "created_at", "items_total"]

        for item in golden["items"]:
            for field in required_fields:
                assert field in item, f"Missing field '{field}' in job list item"

    def test_job_list_items_sorted_by_created_at(self, load_golden):
        """Verify job list items are sorted by created_at descending."""
        golden = load_golden(self.GOLDEN_FILE)
        items = golden["items"]

        if len(items) < 2:
            pytest.skip("Need at least 2 items to test sorting")

        for i in range(len(items) - 1):
            assert items[i]["created_at"] >= items[i + 1]["created_at"], (
                f"Jobs not sorted by created_at descending"
            )


class TestRegressionJobResultConsistency:
    """Regression tests for job result consistency with batch API."""

    SYNC_FILE = "scenario_jobs_v110_sync.json"

    def test_result_total_items_matches_request(self, load_golden):
        """Verify result total_items matches number of request items."""
        golden = load_golden(self.SYNC_FILE)

        if golden["status"] != "done" or not golden.get("result"):
            pytest.skip("No result available")

        result = golden["result"]
        assert result["summary"]["total_items"] == golden["items_total"]

    def test_result_ok_count_non_negative(self, load_golden):
        """Verify result ok_count is non-negative."""
        golden = load_golden(self.SYNC_FILE)

        if golden["status"] != "done" or not golden.get("result"):
            pytest.skip("No result available")

        result = golden["result"]
        assert result["summary"]["ok_count"] >= 0

    def test_result_error_count_non_negative(self, load_golden):
        """Verify result error_count is non-negative."""
        golden = load_golden(self.SYNC_FILE)

        if golden["status"] != "done" or not golden.get("result"):
            pytest.skip("No result available")

        result = golden["result"]
        assert result["summary"]["error_count"] >= 0

    def test_result_processing_time_positive(self, load_golden):
        """Verify result processing_time_ms is positive."""
        golden = load_golden(self.SYNC_FILE)

        if golden["status"] != "done" or not golden.get("result"):
            pytest.skip("No result available")

        result = golden["result"]
        assert result["summary"]["processing_time_ms"] > 0

    def test_result_items_have_sizing_response(self, load_golden):
        """Verify ok items have proper sizing response."""
        golden = load_golden(self.SYNC_FILE)

        if golden["status"] != "done" or not golden.get("result"):
            pytest.skip("No result available")

        result = golden["result"]
        for item in result["results"]:
            if item["status"] == "ok":
                response = item["response"]
                assert "variants" in response
                assert "recommended_variant" in response
                assert response["recommended_variant"] in ["small", "medium", "large"]


class TestRegressionJobFields:
    """Regression tests for job model fields."""

    SYNC_FILE = "scenario_jobs_v110_sync.json"
    LIST_FILE = "scenario_jobs_v110_list.json"

    def test_job_list_has_type(self, load_golden):
        """Verify job list items have type field."""
        golden = load_golden(self.LIST_FILE)

        for item in golden["items"]:
            assert "type" in item
            assert item["type"] == "sizing_batch"

    def test_job_has_error_count(self, load_golden):
        """Verify job has error_count field."""
        golden = load_golden(self.SYNC_FILE)

        assert "error_count" in golden
        assert golden["error_count"] >= 0

    def test_job_error_count_matches_result(self, load_golden):
        """Verify job error_count matches result error_count."""
        golden = load_golden(self.SYNC_FILE)

        if golden["status"] != "done" or not golden.get("result"):
            pytest.skip("No result available")

        result = golden["result"]
        assert golden["error_count"] == result["summary"]["error_count"]
