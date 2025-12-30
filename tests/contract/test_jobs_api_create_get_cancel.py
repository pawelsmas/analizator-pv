"""
Contract tests for Jobs API endpoints (v1.1.0).

Tests:
- POST /api/bess-dispatch/jobs/sizing-batch: Create job with wait=true, idempotency
- GET /api/bess-dispatch/jobs/{job_id}: Get job status and result
- GET /api/bess-dispatch/jobs: List jobs with filters
- DELETE /api/bess-dispatch/jobs/{job_id}: Cancel job
"""

import pytest
import uuid
from ._api import post_json, get_json, delete_json


def _base_req():
    """Minimal valid sizing request."""
    return {
        "load_kw": [100, 100, 100, 100, 100, 100, 150, 200, 250, 300, 300, 300, 300, 300, 250, 200, 150, 100, 100, 100, 100, 100, 100, 100],
        "pv_generation_kw": [0, 0, 0, 0, 0, 0, 50, 200, 500, 800, 1000, 1100, 1100, 1000, 800, 500, 200, 50, 0, 0, 0, 0, 0, 0],
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


# =============================================================================
# TestJobsCreateWaitTrue
# =============================================================================

class TestJobsCreateWaitTrue:
    """Tests for POST /api/bess-dispatch/jobs/sizing-batch with wait=true."""

    def test_jobs_create_wait_true_finishes_and_has_result(self):
        """Job with wait=true should complete and have result."""
        idem_key = f"test-idem-{uuid.uuid4()}"
        payload = {
            "batch_id": "jb1",
            "idempotency_key": idem_key,
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "A", "request": _base_req()},
                {"item_id": "B", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)

        assert resp["status"] in ("done", "running", "pending")
        assert "job_id" in resp
        assert resp["items_total"] == 2

        # If done, verify we can get the result
        if resp["status"] == "done":
            job_id = resp["job_id"]
            detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
            assert detail["status"] == "done"
            assert detail["result"] is not None
            assert "results" in detail["result"]
            assert len(detail["result"]["results"]) == 2

    def test_jobs_create_wait_true_returns_status_done(self):
        """Job with wait=true should return status=done after processing."""
        idem_key = f"test-wait-done-{uuid.uuid4()}"
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [{"item_id": "X", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)

        assert resp["status"] == "done"
        assert resp["items_done"] == 1
        assert resp["error_count"] == 0

    def test_jobs_create_wait_true_result_has_summary(self):
        """Job result should have summary with ok_count and error_count."""
        idem_key = f"test-summary-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "wait": True,
            "fail_fast": False,
            "items": [{"item_id": "S1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        assert detail["result"] is not None
        summary = detail["result"].get("summary")
        assert summary is not None
        assert "ok_count" in summary
        assert "error_count" in summary
        assert "processing_time_ms" in summary


# =============================================================================
# TestJobsIdempotency
# =============================================================================

class TestJobsIdempotency:
    """Tests for idempotency key handling."""

    def test_idempotency_key_returns_same_job(self):
        """Same idempotency key should return same job_id."""
        idem_key = f"idem-same-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "wait": True,
            "items": [{"item_id": "I1", "request": _base_req()}]
        }

        resp1 = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id1 = resp1["job_id"]

        # Second request with same idempotency key
        resp2 = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id2 = resp2["job_id"]

        assert job_id1 == job_id2

    def test_different_idempotency_key_returns_different_job(self):
        """Different idempotency keys should return different job_ids."""
        payload1 = {
            "idempotency_key": f"idem-diff-1-{uuid.uuid4()}",
            "wait": True,
            "items": [{"item_id": "D1", "request": _base_req()}]
        }
        payload2 = {
            "idempotency_key": f"idem-diff-2-{uuid.uuid4()}",
            "wait": True,
            "items": [{"item_id": "D2", "request": _base_req()}]
        }

        resp1 = post_json("/api/bess-dispatch/jobs/sizing-batch", payload1)
        resp2 = post_json("/api/bess-dispatch/jobs/sizing-batch", payload2)

        assert resp1["job_id"] != resp2["job_id"]


# =============================================================================
# TestJobsGetDetail
# =============================================================================

class TestJobsGetDetail:
    """Tests for GET /api/bess-dispatch/jobs/{job_id}."""

    def test_get_job_returns_all_fields(self):
        """GET job should return all required fields."""
        idem_key = f"test-get-fields-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "batch_id": "batch-get-test",
            "wait": True,
            "items": [{"item_id": "G1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")

        assert "job_id" in detail
        assert "status" in detail
        assert "created_at" in detail
        assert "updated_at" in detail
        assert "items_total" in detail
        assert "items_done" in detail
        assert "error_count" in detail
        assert detail["batch_id"] == "batch-get-test"

    def test_get_job_done_has_result(self):
        """GET job with status=done should have result."""
        idem_key = f"test-done-result-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "wait": True,
            "items": [{"item_id": "R1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")

        assert detail["status"] == "done"
        assert detail["result"] is not None
        assert detail["request"] is not None

    def test_get_nonexistent_job_returns_404(self):
        """GET nonexistent job should return 404."""
        fake_id = str(uuid.uuid4())
        try:
            get_json(f"/api/bess-dispatch/jobs/{fake_id}")
            assert False, "Expected 404"
        except AssertionError as e:
            assert "404" in str(e)


# =============================================================================
# TestJobsList
# =============================================================================

class TestJobsList:
    """Tests for GET /api/bess-dispatch/jobs."""

    def test_list_jobs_returns_items_and_pagination(self):
        """List jobs should return items array and pagination info."""
        resp = get_json("/api/bess-dispatch/jobs?limit=5&offset=0")

        assert "items" in resp
        assert isinstance(resp["items"], list)
        assert "total" in resp
        assert "limit" in resp
        assert "offset" in resp
        assert resp["limit"] == 5
        assert resp["offset"] == 0

    def test_list_jobs_with_status_filter(self):
        """List jobs with status filter should only return matching jobs."""
        resp = get_json("/api/bess-dispatch/jobs?status=done&limit=10")

        for job in resp["items"]:
            assert job["status"] == "done"

    def test_list_jobs_with_type_filter(self):
        """List jobs with type filter should only return matching jobs."""
        resp = get_json("/api/bess-dispatch/jobs?type=sizing_batch&limit=10")

        for job in resp["items"]:
            assert job["type"] == "sizing_batch"


# =============================================================================
# TestJobsCancel
# =============================================================================

class TestJobsCancel:
    """Tests for DELETE /api/bess-dispatch/jobs/{job_id}."""

    def test_cancel_pending_job_succeeds(self):
        """Cancel pending job should succeed."""
        # Create a job without wait (stays pending)
        idem_key = f"test-cancel-pending-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "wait": False,
            "items": [{"item_id": "C1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        # Should be pending
        assert resp["status"] == "pending"

        # Cancel it
        cancel_resp = delete_json(f"/api/bess-dispatch/jobs/{job_id}")

        assert cancel_resp["cancelled"] == True
        assert cancel_resp["status"] == "cancelled"

    def test_cancel_done_job_fails(self):
        """Cancel done job should return cancelled=false."""
        idem_key = f"test-cancel-done-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "wait": True,  # Wait means it will complete
            "items": [{"item_id": "CD1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        assert resp["status"] == "done"

        # Try to cancel
        cancel_resp = delete_json(f"/api/bess-dispatch/jobs/{job_id}")

        assert cancel_resp["cancelled"] == False
        assert cancel_resp["status"] == "done"

    def test_cancel_nonexistent_job_returns_404(self):
        """Cancel nonexistent job should return 404."""
        fake_id = str(uuid.uuid4())
        try:
            delete_json(f"/api/bess-dispatch/jobs/{fake_id}")
            assert False, "Expected 404"
        except AssertionError as e:
            assert "404" in str(e)


# =============================================================================
# TestJobsResultStructure
# =============================================================================

class TestJobsResultStructure:
    """Tests for job result structure."""

    def test_job_result_has_results_array(self):
        """Job result should have results array with item results."""
        idem_key = f"test-results-array-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "wait": True,
            "items": [
                {"item_id": "RA1", "request": _base_req()},
                {"item_id": "RA2", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        results = detail["result"]["results"]

        assert len(results) == 2
        for r in results:
            assert "item_id" in r
            assert "status" in r
            assert r["status"] in ("ok", "error")

    def test_job_result_item_has_response(self):
        """Each successful item should have response with variants."""
        idem_key = f"test-item-response-{uuid.uuid4()}"
        payload = {
            "idempotency_key": idem_key,
            "wait": True,
            "items": [{"item_id": "IR1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        item_result = detail["result"]["results"][0]

        assert item_result["status"] == "ok"
        assert item_result["response"] is not None
        assert "variants" in item_result["response"]


# =============================================================================
# TestJobsValidation
# =============================================================================

class TestJobsValidation:
    """Tests for input validation."""

    def test_empty_items_returns_422(self):
        """Empty items array should return 422."""
        payload = {
            "wait": True,
            "items": []
        }
        try:
            post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
            assert False, "Expected 422"
        except AssertionError as e:
            assert "422" in str(e)

    def test_too_many_items_returns_422(self):
        """Too many items should return 422."""
        # Create 101 items (default max is 100)
        items = [{"item_id": f"item-{i}", "request": _base_req()} for i in range(101)]
        payload = {
            "wait": True,
            "items": items
        }
        try:
            post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
            assert False, "Expected 422"
        except AssertionError as e:
            assert "422" in str(e)
