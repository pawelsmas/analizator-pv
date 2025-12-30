"""
Unit tests for JobStore SQLite module (v1.1.0).

Tests core JobStore functionality:
- create_job
- get_job
- list_jobs
- mark_running
- update_progress
- save_result
- cancel
- is_cancelled
- claim_next_pending_job

Run with: pytest tests/unit/test_job_store_create_get_list.py -v
"""

import os
import sys
import tempfile

import pytest

# Add services/bess-dispatch to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/bess-dispatch"))

from job_store import JobStore


class TestJobStoreCreateAndGet:
    """Tests for job creation and retrieval."""

    def test_create_job_returns_job_id(self):
        """Verify create_job returns a job_id."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
                batch_id="b1",
                idempotency_key="idem-1"
            )

            assert job_id is not None
            assert len(job_id) == 36  # UUID format

    def test_get_job_returns_correct_data(self):
        """Verify get_job returns job with correct fields."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
                batch_id="b1",
                idempotency_key="idem-2"
            )

            j = js.get_job(job_id)

            assert j["job_id"] == job_id
            assert j["status"] == "pending"
            assert j["type"] == "sizing_batch"
            assert j["batch_id"] == "b1"
            assert j["idempotency_key"] == "idem-2"
            assert j["items_total"] == 1
            assert j["items_done"] == 0
            assert j["error_count"] == 0

    def test_get_job_nonexistent_returns_none(self):
        """Verify get_job returns None for nonexistent job."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            j = js.get_job("00000000-0000-0000-0000-000000000000")

            assert j is None


class TestJobStoreIdempotency:
    """Tests for idempotency_key behavior."""

    def test_idempotency_key_returns_same_job_id(self):
        """Verify same idempotency_key returns same job_id."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id1 = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
                idempotency_key="idem-same"
            )

            job_id2 = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "B", "request": {"x": 2}}]},
                idempotency_key="idem-same"
            )

            assert job_id1 == job_id2

    def test_different_idempotency_keys_create_different_jobs(self):
        """Verify different idempotency_keys create different jobs."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id1 = js.create_job(
                type="sizing_batch",
                request={"items": []},
                idempotency_key="idem-a"
            )

            job_id2 = js.create_job(
                type="sizing_batch",
                request={"items": []},
                idempotency_key="idem-b"
            )

            assert job_id1 != job_id2


class TestJobStoreList:
    """Tests for list_jobs functionality."""

    def test_list_jobs_returns_items(self):
        """Verify list_jobs returns items array."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            js.create_job(type="sizing_batch", request={"items": []})

            lst = js.list_jobs(limit=10, offset=0)

            assert "items" in lst
            assert "total" in lst
            assert "limit" in lst
            assert "offset" in lst
            assert lst["total"] >= 1
            assert len(lst["items"]) >= 1

    def test_list_jobs_filter_by_status(self):
        """Verify list_jobs can filter by status."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})

            # All new jobs are pending
            lst = js.list_jobs(limit=10, offset=0, status="pending")
            assert any(x["job_id"] == job_id for x in lst["items"])

            # No running jobs
            lst_running = js.list_jobs(limit=10, offset=0, status="running")
            assert not any(x["job_id"] == job_id for x in lst_running["items"])

    def test_list_jobs_filter_by_type(self):
        """Verify list_jobs can filter by type."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})

            lst = js.list_jobs(limit=10, offset=0, type="sizing_batch")
            assert any(x["job_id"] == job_id for x in lst["items"])

            lst_other = js.list_jobs(limit=10, offset=0, type="other_type")
            assert not any(x["job_id"] == job_id for x in lst_other["items"])


class TestJobStoreStatusTransitions:
    """Tests for status transitions."""

    def test_mark_running_changes_status(self):
        """Verify mark_running changes status from pending to running."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})
            assert js.get_job(job_id)["status"] == "pending"

            result = js.mark_running(job_id)
            assert result is True
            assert js.get_job(job_id)["status"] == "running"

    def test_mark_running_fails_for_non_pending(self):
        """Verify mark_running fails for non-pending jobs."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})
            js.mark_running(job_id)  # Now running

            # Try to mark running again
            result = js.mark_running(job_id)
            assert result is False

    def test_update_progress_updates_counts(self):
        """Verify update_progress updates items_done and error_count."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A"}, {"item_id": "B"}]}
            )

            js.update_progress(job_id, items_done=1, error_count=0)
            j = js.get_job(job_id)
            assert j["items_done"] == 1
            assert j["error_count"] == 0

            js.update_progress(job_id, items_done=2, error_count=1)
            j = js.get_job(job_id)
            assert j["items_done"] == 2
            assert j["error_count"] == 1

    def test_save_result_sets_status_and_result(self):
        """Verify save_result sets status and result."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})
            js.mark_running(job_id)

            result_data = {"results": [{"item_id": "A", "status": "ok"}]}
            js.save_result(job_id, result_data, status="done")

            j = js.get_job(job_id)
            assert j["status"] == "done"
            assert j["result"] == result_data


class TestJobStoreCancel:
    """Tests for cancel functionality."""

    def test_cancel_pending_job(self):
        """Verify cancel works for pending job."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})

            result = js.cancel(job_id)
            assert result is True

            j = js.get_job(job_id)
            assert j["status"] == "cancelled"

    def test_cancel_running_job(self):
        """Verify cancel works for running job."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})
            js.mark_running(job_id)

            result = js.cancel(job_id)
            assert result is True

            j = js.get_job(job_id)
            assert j["status"] == "cancelled"

    def test_cancel_done_job_fails(self):
        """Verify cancel fails for done job."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})
            js.save_result(job_id, {"results": []}, status="done")

            result = js.cancel(job_id)
            assert result is False

    def test_is_cancelled_returns_true_for_cancelled(self):
        """Verify is_cancelled returns True for cancelled job."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})
            js.cancel(job_id)

            assert js.is_cancelled(job_id) is True

    def test_is_cancelled_returns_false_for_pending(self):
        """Verify is_cancelled returns False for pending job."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})

            assert js.is_cancelled(job_id) is False


class TestJobStoreClaimNextPending:
    """Tests for claim_next_pending_job."""

    def test_claim_next_pending_returns_oldest(self):
        """Verify claim_next_pending_job returns oldest pending job."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id1 = js.create_job(type="sizing_batch", request={"items": []})
            job_id2 = js.create_job(type="sizing_batch", request={"items": []})

            claimed = js.claim_next_pending_job(type="sizing_batch")
            assert claimed == job_id1

            # First job should now be running
            assert js.get_job(job_id1)["status"] == "running"
            assert js.get_job(job_id2)["status"] == "pending"

    def test_claim_next_pending_returns_none_if_empty(self):
        """Verify claim_next_pending_job returns None if no pending jobs."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            claimed = js.claim_next_pending_job(type="sizing_batch")
            assert claimed is None


class TestJobStorePrune:
    """Tests for prune_old_jobs."""

    def test_prune_does_not_delete_recent_jobs(self):
        """Verify prune does not delete recent jobs."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            job_id = js.create_job(type="sizing_batch", request={"items": []})

            deleted = js.prune_old_jobs(retention_days=30)
            assert deleted == 0

            # Job should still exist
            assert js.get_job(job_id) is not None


class TestJobStoreCountByStatus:
    """Tests for count_by_status."""

    def test_count_by_status_returns_counts(self):
        """Verify count_by_status returns status counts."""
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "jobs.sqlite")
            js = JobStore(db_path=db)

            js.create_job(type="sizing_batch", request={"items": []})
            js.create_job(type="sizing_batch", request={"items": []})

            counts = js.count_by_status()
            assert counts.get("pending", 0) >= 2
