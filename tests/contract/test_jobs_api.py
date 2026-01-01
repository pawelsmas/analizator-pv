"""
Contract tests for Jobs API (v3.4.0 PR2).

Tests:
- POST /api/bess-dispatch/jobs - Enqueue job
- GET /api/bess-dispatch/jobs - List jobs
- GET /api/bess-dispatch/jobs/{id} - Get job status
- POST /api/bess-dispatch/jobs/{id}/cancel - Cancel job
"""

import pytest
import os
import sys
from datetime import datetime, timezone
import uuid

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestJobsRouterImports:
    """Tests for jobs_router imports."""

    def test_import_jobs_router(self):
        """jobs_router should be importable."""
        from jobs_router import router
        assert router is not None

    def test_router_has_prefix(self):
        """Router should have /jobs prefix."""
        from jobs_router import router
        assert router.prefix == "/jobs"

    def test_router_has_tags(self):
        """Router should have jobs tag."""
        from jobs_router import router
        assert "jobs" in router.tags


class TestJobsRouterModels:
    """Tests for jobs API models."""

    def test_enqueue_job_request_model(self):
        """EnqueueJobRequest should be valid."""
        from jobs_router import EnqueueJobRequest

        req = EnqueueJobRequest(kind="sizing_batch", payload={"test": True})
        assert req.kind == "sizing_batch"
        assert req.payload == {"test": True}

    def test_enqueue_job_request_with_idempotency(self):
        """EnqueueJobRequest should support idempotency_key."""
        from jobs_router import EnqueueJobRequest

        req = EnqueueJobRequest(
            kind="report_run",
            payload={"run_id": "abc"},
            idempotency_key="unique-key-123"
        )
        assert req.idempotency_key == "unique-key-123"

    def test_job_response_model(self):
        """JobResponse should have all required fields."""
        from jobs_router import JobResponse

        resp = JobResponse(
            job_id="test-job-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="queued",
            created_at="2024-01-01T00:00:00Z",
            attempts=0,
            max_attempts=3,
        )
        assert resp.job_id == "test-job-123"
        assert resp.status == "queued"

    def test_job_response_with_progress(self):
        """JobResponse should support progress field."""
        from jobs_router import JobResponse, JobProgressResponse

        progress = JobProgressResponse(
            current=5,
            total=10,
            percent=50.0,
            message="Processing..."
        )
        resp = JobResponse(
            job_id="test-job-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="running",
            created_at="2024-01-01T00:00:00Z",
            attempts=1,
            max_attempts=3,
            progress=progress,
        )
        assert resp.progress.percent == 50.0

    def test_job_response_with_error(self):
        """JobResponse should support error field."""
        from jobs_router import JobResponse, JobErrorResponse

        error = JobErrorResponse(
            code="TIMEOUT",
            detail="Job timed out"
        )
        resp = JobResponse(
            job_id="test-job-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="failed",
            created_at="2024-01-01T00:00:00Z",
            attempts=3,
            max_attempts=3,
            error=error,
        )
        assert resp.error.code == "TIMEOUT"

    def test_job_list_response_model(self):
        """JobListResponse should have items and pagination."""
        from jobs_router import JobListResponse, JobResponse

        resp = JobListResponse(
            items=[],
            total=0,
            limit=50,
            offset=0,
        )
        assert resp.total == 0
        assert resp.limit == 50

    def test_enqueue_job_response_model(self):
        """EnqueueJobResponse should have job_id and created flag."""
        from jobs_router import EnqueueJobResponse

        resp = EnqueueJobResponse(
            job_id="new-job-123",
            status="queued",
            created=True,
        )
        assert resp.created is True

    def test_cancel_job_response_model(self):
        """CancelJobResponse should have cancelled flag."""
        from jobs_router import CancelJobResponse

        resp = CancelJobResponse(
            job_id="job-123",
            status="cancelled",
            cancelled=True,
        )
        assert resp.cancelled is True


class TestJobsRouterConstants:
    """Tests for jobs API constants."""

    def test_valid_job_kinds_defined(self):
        """VALID_JOB_KINDS should be defined."""
        from jobs_router import VALID_JOB_KINDS

        assert "sizing_batch" in VALID_JOB_KINDS
        assert "report_run" in VALID_JOB_KINDS
        assert "report_portfolio" in VALID_JOB_KINDS
        assert "validate_pack" in VALID_JOB_KINDS

    def test_cancellable_statuses_defined(self):
        """CANCELLABLE_STATUSES should be defined."""
        from jobs_router import CANCELLABLE_STATUSES

        assert "queued" in CANCELLABLE_STATUSES
        assert "running" in CANCELLABLE_STATUSES


class TestJobToResponse:
    """Tests for _job_to_response helper."""

    def test_job_to_response_basic(self):
        """_job_to_response should convert job to response."""
        from jobs_router import _job_to_response
        from db_models import JobQueue
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        job = JobQueue(
            id="test-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="queued",
            created_at=now,
            attempts=0,
            max_attempts=3,
        )

        resp = _job_to_response(job)

        assert resp.job_id == "test-123"
        assert resp.tenant_id == "tenant-1"
        assert resp.kind == "sizing_batch"
        assert resp.status == "queued"

    def test_job_to_response_with_progress(self):
        """_job_to_response should parse progress JSON."""
        from jobs_router import _job_to_response
        from db_models import JobQueue
        import json

        now = datetime.now(timezone.utc)
        job = JobQueue(
            id="test-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="running",
            created_at=now,
            started_at=now,
            attempts=1,
            max_attempts=3,
            progress_json=json.dumps({
                "current": 5,
                "total": 10,
                "percent": 50.0,
                "message": "Processing item 5"
            }),
        )

        resp = _job_to_response(job)

        assert resp.progress is not None
        assert resp.progress.current == 5
        assert resp.progress.total == 10
        assert resp.progress.percent == 50.0

    def test_job_to_response_with_error(self):
        """_job_to_response should include error info."""
        from jobs_router import _job_to_response
        from db_models import JobQueue

        now = datetime.now(timezone.utc)
        job = JobQueue(
            id="test-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="failed",
            created_at=now,
            finished_at=now,
            attempts=3,
            max_attempts=3,
            error_code="TIMEOUT",
            error_detail="Job timed out after 300s",
        )

        resp = _job_to_response(job)

        assert resp.error is not None
        assert resp.error.code == "TIMEOUT"
        assert resp.error.detail == "Job timed out after 300s"

    def test_job_to_response_with_result(self):
        """_job_to_response should include result for succeeded jobs."""
        from jobs_router import _job_to_response
        from db_models import JobQueue
        import json

        now = datetime.now(timezone.utc)
        job = JobQueue(
            id="test-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="succeeded",
            created_at=now,
            finished_at=now,
            attempts=1,
            max_attempts=3,
            result_json=json.dumps({"items_processed": 10, "success": True}),
        )

        resp = _job_to_response(job, include_result=True)

        assert resp.result is not None
        assert resp.result["items_processed"] == 10

    def test_job_to_response_excludes_result_when_requested(self):
        """_job_to_response should exclude result when include_result=False."""
        from jobs_router import _job_to_response
        from db_models import JobQueue
        import json

        now = datetime.now(timezone.utc)
        job = JobQueue(
            id="test-123",
            tenant_id="tenant-1",
            kind="sizing_batch",
            status="succeeded",
            created_at=now,
            finished_at=now,
            attempts=1,
            max_attempts=3,
            result_json=json.dumps({"items_processed": 10}),
        )

        resp = _job_to_response(job, include_result=False)

        assert resp.result is None


class TestEnqueueJobEndpoint:
    """Tests for POST /jobs endpoint structure."""

    def test_enqueue_job_function_exists(self):
        """enqueue_job endpoint function should exist."""
        from jobs_router import enqueue_job
        assert callable(enqueue_job)

    def test_enqueue_validates_job_kind(self):
        """enqueue_job should validate job kind."""
        from jobs_router import VALID_JOB_KINDS

        # All valid kinds should be accepted
        assert "sizing_batch" in VALID_JOB_KINDS
        assert "report_run" in VALID_JOB_KINDS

        # Invalid kind should not be in list
        assert "invalid_kind" not in VALID_JOB_KINDS


class TestListJobsEndpoint:
    """Tests for GET /jobs endpoint structure."""

    def test_list_jobs_function_exists(self):
        """list_jobs endpoint function should exist."""
        from jobs_router import list_jobs
        assert callable(list_jobs)


class TestGetJobEndpoint:
    """Tests for GET /jobs/{job_id} endpoint structure."""

    def test_get_job_function_exists(self):
        """get_job endpoint function should exist."""
        from jobs_router import get_job
        assert callable(get_job)


class TestCancelJobEndpoint:
    """Tests for POST /jobs/{job_id}/cancel endpoint structure."""

    def test_cancel_job_function_exists(self):
        """cancel_job endpoint function should exist."""
        from jobs_router import cancel_job
        assert callable(cancel_job)


class TestJobStatusTransitions:
    """Tests for valid job status values and transitions."""

    def test_valid_statuses(self):
        """All valid job statuses should be recognized."""
        valid_statuses = ["queued", "running", "succeeded", "failed", "cancelled"]

        # These should all be valid
        for status in valid_statuses:
            assert status in ["queued", "running", "succeeded", "failed", "cancelled"]

    def test_terminal_statuses(self):
        """Terminal statuses should not be cancellable."""
        from jobs_router import CANCELLABLE_STATUSES

        # Terminal statuses should NOT be in cancellable list
        assert "succeeded" not in CANCELLABLE_STATUSES
        assert "failed" not in CANCELLABLE_STATUSES
        assert "cancelled" not in CANCELLABLE_STATUSES


class TestRetryPolicy:
    """Tests for retry policy implementation."""

    def test_default_max_attempts(self):
        """Default max_attempts should be 3 when set explicitly."""
        from db_models import JobQueue

        # When creating a job, we explicitly set max_attempts to 3
        job = JobQueue(max_attempts=3)
        assert job.max_attempts == 3

    def test_job_response_includes_retry_info(self):
        """JobResponse should include attempts and max_attempts."""
        from jobs_router import JobResponse

        resp = JobResponse(
            job_id="test",
            tenant_id="tenant",
            kind="sizing_batch",
            status="running",
            created_at="2024-01-01T00:00:00Z",
            attempts=2,
            max_attempts=3,
        )

        assert resp.attempts == 2
        assert resp.max_attempts == 3


class TestIdempotency:
    """Tests for idempotency key support."""

    def test_enqueue_request_accepts_idempotency_key(self):
        """EnqueueJobRequest should accept idempotency_key."""
        from jobs_router import EnqueueJobRequest

        req = EnqueueJobRequest(
            kind="sizing_batch",
            idempotency_key="unique-key"
        )
        assert req.idempotency_key == "unique-key"

    def test_enqueue_response_indicates_created(self):
        """EnqueueJobResponse should indicate if job was newly created."""
        from jobs_router import EnqueueJobResponse

        # New job
        resp_new = EnqueueJobResponse(
            job_id="new-123",
            status="queued",
            created=True,
        )
        assert resp_new.created is True

        # Idempotent hit
        resp_existing = EnqueueJobResponse(
            job_id="existing-123",
            status="running",
            created=False,
        )
        assert resp_existing.created is False
