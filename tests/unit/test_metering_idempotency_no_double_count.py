"""
Unit tests for usage metering idempotency.

Tests verify that:
- Counters are metered correctly
- Idempotency keys prevent double counting
- Different actions are tracked separately
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from usage_metering import (
    meter_counter,
    meter_bytes,
    meter_job_enqueued,
    meter_run_created,
    meter_report_generated,
    meter_share_created,
    meter_artifact_written,
    get_today_usage,
    is_already_metered,
    mark_as_metered,
    clear_metered_keys,
    get_quota_store,
)
import usage_metering


class TestMeteringIdempotency:
    """Test idempotency of metering functions."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Set up test environment."""
        # Create temp database
        fd, self.temp_db = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)

        # Enable metering and set temp db
        monkeypatch.setenv("METERING_ENABLED", "true")
        monkeypatch.setenv("QUOTA_STORE_PATH", self.temp_db)

        # Reset module state - force new quota store
        usage_metering._quota_store = None
        clear_metered_keys()

        # Create fresh store with new db
        from quota_store import QuotaStore
        usage_metering._quota_store = QuotaStore(db_path=self.temp_db)

        yield

        # Cleanup
        usage_metering._quota_store = None
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_meter_counter_increments_usage(self):
        """meter_counter should increment the counter."""
        result = meter_counter("tenant-1", "project-1", "test_counter")
        assert result is True

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["test_counter"] == 1

    def test_meter_counter_respects_idempotency(self):
        """Same idempotency key should not double count."""
        meter_counter(
            "tenant-1", "project-1", "test_counter",
            idempotency_key="key-1"
        )
        result = meter_counter(
            "tenant-1", "project-1", "test_counter",
            idempotency_key="key-1"
        )

        assert result is False  # Should be skipped

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["test_counter"] == 1  # Still 1

    def test_meter_counter_different_keys_not_idempotent(self):
        """Different idempotency keys should both count."""
        meter_counter(
            "tenant-1", "project-1", "test_counter",
            idempotency_key="key-1"
        )
        meter_counter(
            "tenant-1", "project-1", "test_counter",
            idempotency_key="key-2"
        )

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["test_counter"] == 2

    def test_meter_counter_no_key_always_counts(self):
        """Without idempotency key, every call counts."""
        meter_counter("tenant-1", "project-1", "test_counter")
        meter_counter("tenant-1", "project-1", "test_counter")
        meter_counter("tenant-1", "project-1", "test_counter")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["test_counter"] == 3

    def test_meter_bytes_increments_usage(self):
        """meter_bytes should increment bytes counter."""
        result = meter_bytes("tenant-1", "project-1", "test_bytes", 1024)
        assert result is True

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["bytes"]["test_bytes"] == 1024

    def test_meter_bytes_respects_idempotency(self):
        """Same idempotency key should not double count bytes."""
        meter_bytes(
            "tenant-1", "project-1", "test_bytes", 1024,
            idempotency_key="artifact-1"
        )
        result = meter_bytes(
            "tenant-1", "project-1", "test_bytes", 2048,
            idempotency_key="artifact-1"
        )

        assert result is False

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["bytes"]["test_bytes"] == 1024  # First value only

    def test_different_actions_separate_idempotency(self):
        """Same key for different actions should both count."""
        meter_counter(
            "tenant-1", "project-1", "action_a",
            idempotency_key="key-1"
        )
        meter_counter(
            "tenant-1", "project-1", "action_b",
            idempotency_key="key-1"
        )

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["action_a"] == 1
        assert usage["counters"]["action_b"] == 1

    def test_different_projects_separate_idempotency(self):
        """Same key in different projects should both count."""
        meter_counter(
            "tenant-1", "project-1", "test_counter",
            idempotency_key="key-1"
        )
        meter_counter(
            "tenant-1", "project-2", "test_counter",
            idempotency_key="key-1"
        )

        usage1 = get_today_usage("tenant-1", "project-1")
        usage2 = get_today_usage("tenant-1", "project-2")

        assert usage1["counters"]["test_counter"] == 1
        assert usage2["counters"]["test_counter"] == 1


class TestConvenienceFunctions:
    """Test convenience metering functions."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Set up test environment."""
        fd, self.temp_db = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)

        monkeypatch.setenv("METERING_ENABLED", "true")
        monkeypatch.setenv("QUOTA_STORE_PATH", self.temp_db)

        usage_metering._quota_store = None
        clear_metered_keys()

        # Create fresh store with new db
        from quota_store import QuotaStore
        usage_metering._quota_store = QuotaStore(db_path=self.temp_db)

        yield

        usage_metering._quota_store = None
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_meter_job_enqueued(self):
        """meter_job_enqueued should record jobs_enqueued."""
        meter_job_enqueued("tenant-1", "project-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["jobs_enqueued"] == 1

    def test_meter_job_enqueued_idempotent(self):
        """meter_job_enqueued should respect idempotency."""
        meter_job_enqueued("tenant-1", "project-1", idempotency_key="job-1")
        meter_job_enqueued("tenant-1", "project-1", idempotency_key="job-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["jobs_enqueued"] == 1

    def test_meter_run_created(self):
        """meter_run_created should record runs_created."""
        meter_run_created("tenant-1", "project-1", run_id="run-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["runs_created"] == 1

    def test_meter_report_generated(self):
        """meter_report_generated should record reports_generated."""
        meter_report_generated("tenant-1", "project-1", report_id="report-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["reports_generated"] == 1

    def test_meter_share_created(self):
        """meter_share_created should record shares_created."""
        meter_share_created("tenant-1", "project-1", share_id="share-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["counters"]["shares_created"] == 1

    def test_meter_artifact_written(self):
        """meter_artifact_written should record bytes."""
        meter_artifact_written("tenant-1", "project-1", 2048, artifact_id="artifact-1")

        usage = get_today_usage("tenant-1", "project-1")
        assert usage["bytes"]["artifact_bytes_written"] == 2048


class TestIsAlreadyMetered:
    """Test idempotency helper functions."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset metered keys before each test."""
        clear_metered_keys()
        yield

    def test_not_metered_initially(self):
        """is_already_metered should return False for new key."""
        result = is_already_metered("t1", "p1", "key-1", "action")
        assert result is False

    def test_metered_after_marking(self):
        """is_already_metered should return True after marking."""
        mark_as_metered("t1", "p1", "key-1", "action")
        result = is_already_metered("t1", "p1", "key-1", "action")
        assert result is True

    def test_different_action_not_metered(self):
        """Different action should not be marked as metered."""
        mark_as_metered("t1", "p1", "key-1", "action_a")
        result = is_already_metered("t1", "p1", "key-1", "action_b")
        assert result is False

    def test_none_key_never_metered(self):
        """None idempotency key should never be marked as metered."""
        mark_as_metered("t1", "p1", None, "action")
        result = is_already_metered("t1", "p1", None, "action")
        assert result is False

    def test_clear_resets_all(self):
        """clear_metered_keys should reset all tracking."""
        mark_as_metered("t1", "p1", "key-1", "action")
        clear_metered_keys()
        result = is_already_metered("t1", "p1", "key-1", "action")
        assert result is False


class TestMeteringDisabled:
    """Test behavior when metering is disabled."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Disable metering."""
        monkeypatch.setenv("METERING_ENABLED", "false")

        # Reload module to pick up env change
        import importlib
        importlib.reload(usage_metering)

        yield

        # Re-enable for other tests
        monkeypatch.setenv("METERING_ENABLED", "true")
        importlib.reload(usage_metering)

    def test_meter_counter_returns_false_when_disabled(self):
        """meter_counter should return False when disabled."""
        result = meter_counter("tenant-1", "project-1", "test_counter")
        assert result is False

    def test_meter_bytes_returns_false_when_disabled(self):
        """meter_bytes should return False when disabled."""
        result = meter_bytes("tenant-1", "project-1", "test_bytes", 1024)
        assert result is False


class TestGetTodayUsage:
    """Test get_today_usage function."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Set up test environment."""
        fd, self.temp_db = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)

        monkeypatch.setenv("METERING_ENABLED", "true")
        monkeypatch.setenv("QUOTA_STORE_PATH", self.temp_db)

        usage_metering._quota_store = None
        clear_metered_keys()

        # Create fresh store with new db
        from quota_store import QuotaStore
        usage_metering._quota_store = QuotaStore(db_path=self.temp_db)

        yield

        usage_metering._quota_store = None
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_returns_empty_for_no_usage(self):
        """Should return empty counters/bytes for new tenant/project."""
        usage = get_today_usage("new-tenant", "new-project")

        assert "date" in usage
        assert usage["counters"] == {}
        assert usage["bytes"] == {}

    def test_returns_accumulated_usage(self):
        """Should return accumulated usage."""
        meter_counter("tenant-1", "project-1", "counter_a")
        meter_counter("tenant-1", "project-1", "counter_a")
        meter_counter("tenant-1", "project-1", "counter_b")
        meter_bytes("tenant-1", "project-1", "bytes_a", 1024)

        usage = get_today_usage("tenant-1", "project-1")

        assert usage["counters"]["counter_a"] == 2
        assert usage["counters"]["counter_b"] == 1
        assert usage["bytes"]["bytes_a"] == 1024
