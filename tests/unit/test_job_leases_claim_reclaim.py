"""
Unit tests for v1.2.0 job leasing/reclaim/heartbeat functionality.

Tests verify:
- Atomic claim of pending jobs with lease_owner and lease_expires_at
- Reclaim of running jobs with expired leases
- Lease renewal (heartbeat)
- Attempts tracking and max_attempts limit
"""
import os
import sys
import tempfile

import pytest

# Add services directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from job_store import JobStore


class TestClaimNextJob:
    """Test claim_next_job functionality."""

    def test_claim_pending_job(self):
        """Verify pending job is claimed with lease."""
        with tempfile.TemporaryDirectory() as td:
            js = JobStore(
                db_path=os.path.join(td, "jobs.sqlite"),
                worker_id="w1",
                lease_seconds=10,
            )
            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
                batch_id="b",
                idempotency_key=None,
            )

            claimed_id = js.claim_next_job(type="sizing_batch")
            assert claimed_id == job_id

            # Verify job is now running with lease info
            job = js.get_job(job_id)
            assert job["status"] == "running"
            assert job["lease_owner"] == "w1"
            assert job["lease_expires_at"] is not None
            assert job["attempts"] == 1

    def test_second_worker_cannot_claim_active_lease(self):
        """Verify second worker cannot claim job with active lease."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "jobs.sqlite")

            js1 = JobStore(db_path=db_path, worker_id="w1", lease_seconds=10)
            job_id = js1.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
                batch_id="b",
            )

            # Worker 1 claims
            c1 = js1.claim_next_job(type="sizing_batch")
            assert c1 == job_id

            # Worker 2 tries to claim - should get None (no available jobs)
            js2 = JobStore(db_path=db_path, worker_id="w2", lease_seconds=10)
            c2 = js2.claim_next_job(type="sizing_batch")
            assert c2 is None

    def test_claim_pending_then_reclaim_expired_running(self):
        """Full scenario: claim, expire, reclaim by different worker."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "jobs.sqlite")

            js1 = JobStore(db_path=db_path, worker_id="w1", lease_seconds=10)
            job_id = js1.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
                batch_id="b",
                idempotency_key=None,
            )

            # Worker 1 claims
            c1 = js1.claim_next_job(type="sizing_batch")
            assert c1 == job_id

            # Worker 2 cannot claim yet
            js2 = JobStore(db_path=db_path, worker_id="w2", lease_seconds=10)
            c2 = js2.claim_next_job(type="sizing_batch")
            assert c2 is None

            # Force expire the lease
            js1.force_set_lease_expired(job_id)

            # Now worker 2 can reclaim
            c3 = js2.claim_next_job(type="sizing_batch")
            assert c3 == job_id

            # Verify new lease owner
            job = js2.get_job(job_id)
            assert job["lease_owner"] == "w2"
            assert job["attempts"] == 2

    def test_no_claim_when_max_attempts_exceeded(self):
        """Verify job is not claimed when max_attempts exceeded."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "jobs.sqlite")

            js = JobStore(db_path=db_path, worker_id="w1", lease_seconds=10)
            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
                batch_id="b",
            )

            # Claim and expire 3 times (default max_attempts)
            for i in range(3):
                claimed = js.claim_next_job(type="sizing_batch")
                assert claimed == job_id, f"Should claim on attempt {i+1}"
                js.force_set_lease_expired(job_id)

            # 4th attempt should fail
            claimed = js.claim_next_job(type="sizing_batch")
            assert claimed is None


class TestRenewLease:
    """Test lease renewal (heartbeat) functionality."""

    def test_renew_lease_success(self):
        """Verify lease can be renewed by owner."""
        with tempfile.TemporaryDirectory() as td:
            js = JobStore(
                db_path=os.path.join(td, "jobs.sqlite"),
                worker_id="w1",
                lease_seconds=10,
            )
            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
            )

            js.claim_next_job(type="sizing_batch")
            job_before = js.get_job(job_id)
            old_expires = job_before["lease_expires_at"]

            # Renew lease
            import time
            time.sleep(0.1)  # Small delay to ensure time difference
            result = js.renew_lease(job_id)
            assert result is True

            job_after = js.get_job(job_id)
            assert job_after["lease_expires_at"] > old_expires

    def test_renew_lease_fails_for_non_owner(self):
        """Verify lease cannot be renewed by non-owner."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "jobs.sqlite")

            js1 = JobStore(db_path=db_path, worker_id="w1", lease_seconds=10)
            job_id = js1.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
            )

            js1.claim_next_job(type="sizing_batch")

            # Worker 2 tries to renew - should fail
            js2 = JobStore(db_path=db_path, worker_id="w2", lease_seconds=10)
            result = js2.renew_lease(job_id)
            assert result is False


class TestMarkDoneFailedCancelled:
    """Test mark_done, mark_failed, mark_cancelled methods."""

    def test_mark_done_clears_lease(self):
        """Verify mark_done clears lease info."""
        with tempfile.TemporaryDirectory() as td:
            js = JobStore(
                db_path=os.path.join(td, "jobs.sqlite"),
                worker_id="w1",
                lease_seconds=10,
            )
            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
            )

            js.claim_next_job(type="sizing_batch")
            js.mark_done(job_id, {"results": []})

            job = js.get_job(job_id)
            assert job["status"] == "done"
            assert job["lease_owner"] is None
            assert job["lease_expires_at"] is None
            assert job["finished_at"] is not None

    def test_mark_failed_records_error(self):
        """Verify mark_failed records last_error."""
        with tempfile.TemporaryDirectory() as td:
            js = JobStore(
                db_path=os.path.join(td, "jobs.sqlite"),
                worker_id="w1",
                lease_seconds=10,
            )
            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
            )

            js.claim_next_job(type="sizing_batch")
            js.mark_failed(job_id, "Processing error: timeout")

            job = js.get_job(job_id)
            assert job["status"] == "failed"
            assert job["last_error"] == "Processing error: timeout"
            assert job["lease_owner"] is None
            assert job["finished_at"] is not None

    def test_mark_cancelled(self):
        """Verify mark_cancelled clears lease."""
        with tempfile.TemporaryDirectory() as td:
            js = JobStore(
                db_path=os.path.join(td, "jobs.sqlite"),
                worker_id="w1",
                lease_seconds=10,
            )
            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
            )

            js.claim_next_job(type="sizing_batch")
            js.mark_cancelled(job_id)

            job = js.get_job(job_id)
            assert job["status"] == "cancelled"
            assert job["lease_owner"] is None
            assert job["finished_at"] is not None


class TestStartedAtFinishedAt:
    """Test started_at and finished_at timestamps."""

    def test_started_at_set_on_first_claim(self):
        """Verify started_at is set only on first claim."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "jobs.sqlite")

            js = JobStore(db_path=db_path, worker_id="w1", lease_seconds=10)
            job_id = js.create_job(
                type="sizing_batch",
                request={"items": [{"item_id": "A", "request": {"x": 1}}]},
            )

            # First claim
            js.claim_next_job(type="sizing_batch")
            job = js.get_job(job_id)
            started_at_1 = job["started_at"]
            assert started_at_1 is not None

            # Expire and reclaim
            js.force_set_lease_expired(job_id)
            js.claim_next_job(type="sizing_batch")
            job = js.get_job(job_id)
            started_at_2 = job["started_at"]

            # started_at should not change
            assert started_at_2 == started_at_1


class TestMigration:
    """Test schema migration for existing databases."""

    def test_migration_adds_new_columns(self):
        """Verify migration adds leasing columns to existing DB."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "jobs.sqlite")

            # Create DB with old schema (manually)
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    batch_id TEXT,
                    idempotency_key TEXT UNIQUE,
                    items_total INTEGER NOT NULL DEFAULT 0,
                    items_done INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    request_hash TEXT NOT NULL,
                    request_blob BLOB NOT NULL,
                    result_blob BLOB,
                    message TEXT
                )
            """)
            conn.commit()
            conn.close()

            # Open with new JobStore - should migrate
            js = JobStore(db_path=db_path, worker_id="w1", lease_seconds=10)

            # Verify new columns exist by querying
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("PRAGMA table_info(jobs)")
            columns = {row["name"] for row in cursor.fetchall()}
            conn.close()

            assert "lease_owner" in columns
            assert "lease_expires_at" in columns
            assert "attempts" in columns
            assert "max_attempts" in columns
            assert "started_at" in columns
            assert "finished_at" in columns
            assert "last_error" in columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
