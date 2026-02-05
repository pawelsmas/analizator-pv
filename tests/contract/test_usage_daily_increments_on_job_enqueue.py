"""
Contract tests for usage metering on job enqueue.

Tests verify that usage counters are incremented when jobs are enqueued.
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from usage_metering import (
    meter_job_enqueued,
    get_today_usage,
    clear_metered_keys,
)
import usage_metering
from quota_store import QuotaStore


class TestUsageDailyIncrementsOnJobEnqueue:
    """Test that job enqueue increments usage counters."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Set up test environment."""
        # Create temp database
        fd, self.temp_db = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)

        # Enable metering
        monkeypatch.setenv("METERING_ENABLED", "true")
        monkeypatch.setenv("QUOTA_STORE_PATH", self.temp_db)

        # Reset module state
        usage_metering._quota_store = None
        clear_metered_keys()

        # Create fresh store
        usage_metering._quota_store = QuotaStore(db_path=self.temp_db)

        yield

        usage_metering._quota_store = None
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_job_enqueue_increments_counter(self):
        """Enqueuing a job should increment jobs_enqueued counter."""
        # Enqueue a job
        meter_job_enqueued("tenant-1", "project-1")

        # Check usage
        usage = get_today_usage("tenant-1", "project-1")
        assert "jobs_enqueued" in usage["counters"]
        assert usage["counters"]["jobs_enqueued"] == 1

    def test_multiple_job_enqueues_increment(self):
        """Multiple job enqueues should increment counter."""
        meter_job_enqueued("tenant-1", "project-1")
        meter_job_enqueued("tenant-1", "project-1")
        meter_job_enqueued("tenant-1", "project-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["jobs_enqueued"] == 3

    def test_idempotent_job_enqueue_no_double_count(self):
        """Same idempotency key should not double count."""
        meter_job_enqueued("tenant-1", "project-1", idempotency_key="job-123")
        meter_job_enqueued("tenant-1", "project-1", idempotency_key="job-123")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["jobs_enqueued"] == 1

    def test_different_idempotency_keys_both_count(self):
        """Different idempotency keys should both count."""
        meter_job_enqueued("tenant-1", "project-1", idempotency_key="job-1")
        meter_job_enqueued("tenant-1", "project-1", idempotency_key="job-2")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["jobs_enqueued"] == 2

    def test_separate_projects_counted_separately(self):
        """Different projects should have separate counters."""
        meter_job_enqueued("tenant-1", "project-1")
        meter_job_enqueued("tenant-1", "project-2")
        meter_job_enqueued("tenant-1", "project-2")

        usage1 = get_today_usage("tenant-1", "project-1")
        usage2 = get_today_usage("tenant-1", "project-2")

        assert usage1["counters"]["jobs_enqueued"] == 1
        assert usage2["counters"]["jobs_enqueued"] == 2

    def test_usage_includes_date(self):
        """Usage response should include today's date."""
        meter_job_enqueued("tenant-1", "project-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert "date" in usage
        # Date should be in YYYY-MM-DD format
        assert len(usage["date"]) == 10
        assert usage["date"].count("-") == 2
