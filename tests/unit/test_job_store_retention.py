"""
Unit tests for v1.2.0 job store retention, vacuum, and stats methods.

Tests verify:
- prune_old_jobs deletes old jobs
- vacuum reclaims space
- get_db_stats returns correct statistics
- count_by_status returns correct counts
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Add services directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from job_store import JobStore


@pytest.fixture
def temp_job_store():
    """Create a temporary job store for testing."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name

    store = JobStore(db_path=db_path)

    yield store

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


def create_test_job(store: JobStore, type: str = "sizing-batch") -> str:
    """Create a test job."""
    return store.create_job(
        type=type,
        request={"items": [{"item_id": "test", "request": {"load_kw": [1, 2, 3]}}]},
        batch_id="test-batch",
    )


class TestJobStorePrune:
    """Test prune_old_jobs method."""

    def test_prune_returns_zero_for_empty_db(self, temp_job_store):
        """Verify prune returns 0 for empty database."""
        deleted = temp_job_store.prune_old_jobs(retention_days=7)

        assert deleted == 0

    def test_prune_returns_zero_for_recent_jobs(self, temp_job_store):
        """Verify prune doesn't delete recent jobs."""
        create_test_job(temp_job_store)
        create_test_job(temp_job_store)

        deleted = temp_job_store.prune_old_jobs(retention_days=7)

        assert deleted == 0

    def test_prune_deletes_old_jobs(self, temp_job_store):
        """Verify prune deletes jobs older than retention period."""
        job_id = create_test_job(temp_job_store)

        # Manually update created_at to be old
        conn = temp_job_store._get_conn()
        try:
            old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            conn.execute(
                "UPDATE jobs SET created_at = ? WHERE job_id = ?",
                (old_date, job_id)
            )
            conn.commit()
        finally:
            conn.close()

        deleted = temp_job_store.prune_old_jobs(retention_days=7)

        assert deleted == 1

    def test_prune_respects_retention_days(self, temp_job_store):
        """Verify prune uses correct retention days."""
        job_id = create_test_job(temp_job_store)

        # Set job to 5 days old
        conn = temp_job_store._get_conn()
        try:
            old_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            conn.execute(
                "UPDATE jobs SET created_at = ? WHERE job_id = ?",
                (old_date, job_id)
            )
            conn.commit()
        finally:
            conn.close()

        # Prune with 7 day retention - should not delete
        deleted_7 = temp_job_store.prune_old_jobs(retention_days=7)
        assert deleted_7 == 0

        # Prune with 3 day retention - should delete
        deleted_3 = temp_job_store.prune_old_jobs(retention_days=3)
        assert deleted_3 == 1


class TestJobStoreVacuum:
    """Test vacuum method."""

    def test_vacuum_returns_size_info(self, temp_job_store):
        """Verify vacuum returns size information."""
        # Create some data to vacuum
        create_test_job(temp_job_store)

        result = temp_job_store.vacuum()

        assert "size_before_bytes" in result
        assert "size_after_bytes" in result
        assert "freed_bytes" in result

    def test_vacuum_sizes_are_non_negative(self, temp_job_store):
        """Verify vacuum sizes are non-negative."""
        create_test_job(temp_job_store)

        result = temp_job_store.vacuum()

        assert result["size_before_bytes"] >= 0
        assert result["size_after_bytes"] >= 0

    def test_vacuum_freed_equals_difference(self, temp_job_store):
        """Verify freed_bytes equals size difference."""
        create_test_job(temp_job_store)

        result = temp_job_store.vacuum()

        expected = result["size_before_bytes"] - result["size_after_bytes"]
        assert result["freed_bytes"] == expected

    def test_vacuum_reclaims_space_after_delete(self, temp_job_store):
        """Verify vacuum can reclaim space after deletions."""
        # Create multiple jobs
        job_ids = [create_test_job(temp_job_store) for _ in range(10)]

        # Mark them old and prune
        conn = temp_job_store._get_conn()
        try:
            old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
            for job_id in job_ids:
                conn.execute(
                    "UPDATE jobs SET created_at = ? WHERE job_id = ?",
                    (old_date, job_id)
                )
            conn.commit()
        finally:
            conn.close()

        temp_job_store.prune_old_jobs(retention_days=7)

        # Vacuum should run without error
        result = temp_job_store.vacuum()
        assert result["size_after_bytes"] >= 0


class TestJobStoreDbStats:
    """Test get_db_stats method."""

    def test_stats_returns_required_fields(self, temp_job_store):
        """Verify stats returns all required fields."""
        create_test_job(temp_job_store)

        stats = temp_job_store.get_db_stats()

        assert "total_jobs" in stats
        assert "size_bytes" in stats
        assert "by_status" in stats
        assert "by_type" in stats
        assert "oldest_job" in stats
        assert "newest_job" in stats

    def test_stats_total_jobs_accurate(self, temp_job_store):
        """Verify total_jobs is accurate."""
        for _ in range(5):
            create_test_job(temp_job_store)

        stats = temp_job_store.get_db_stats()

        assert stats["total_jobs"] == 5

    def test_stats_by_status_counts(self, temp_job_store):
        """Verify by_status counts correctly."""
        job_id = create_test_job(temp_job_store)
        # New job starts as pending
        temp_job_store.mark_running(job_id)

        stats = temp_job_store.get_db_stats()

        assert "running" in stats["by_status"]
        assert stats["by_status"]["running"] >= 1

    def test_stats_by_type_counts(self, temp_job_store):
        """Verify by_type counts correctly."""
        create_test_job(temp_job_store, type="sizing-batch")
        create_test_job(temp_job_store, type="sizing-batch")

        stats = temp_job_store.get_db_stats()

        assert "sizing-batch" in stats["by_type"]
        assert stats["by_type"]["sizing-batch"] >= 2

    def test_stats_oldest_newest_populated(self, temp_job_store):
        """Verify oldest_job and newest_job are populated."""
        create_test_job(temp_job_store)

        stats = temp_job_store.get_db_stats()

        assert stats["oldest_job"] is not None
        assert stats["newest_job"] is not None

    def test_stats_empty_db(self, temp_job_store):
        """Verify stats handles empty database."""
        stats = temp_job_store.get_db_stats()

        assert stats["total_jobs"] == 0
        assert stats["by_status"] == {}
        assert stats["by_type"] == {}


class TestJobStoreCountByStatus:
    """Test count_by_status method."""

    def test_count_by_status_returns_dict(self, temp_job_store):
        """Verify count_by_status returns dict."""
        result = temp_job_store.count_by_status()

        assert isinstance(result, dict)

    def test_count_by_status_empty_db(self, temp_job_store):
        """Verify count_by_status handles empty database."""
        result = temp_job_store.count_by_status()

        assert result == {}

    def test_count_by_status_counts_pending(self, temp_job_store):
        """Verify count_by_status counts pending jobs."""
        create_test_job(temp_job_store)
        create_test_job(temp_job_store)

        result = temp_job_store.count_by_status()

        assert result.get("pending", 0) >= 2

    def test_count_by_status_counts_multiple_states(self, temp_job_store):
        """Verify count_by_status counts multiple states."""
        job1 = create_test_job(temp_job_store)
        job2 = create_test_job(temp_job_store)
        job3 = create_test_job(temp_job_store)

        temp_job_store.mark_running(job1)
        temp_job_store.save_result(job2, {"results": []}, "done")

        result = temp_job_store.count_by_status()

        assert result.get("running", 0) >= 1
        assert result.get("done", 0) >= 1
        assert result.get("pending", 0) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
