"""
Unit tests for usage_daily upsert idempotency.

Tests verify that usage counters are properly incremented atomically
and that the upsert operation works correctly for both new and existing records.
"""

import os
import tempfile
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from quota_store import QuotaStore


class TestUsageDailyUpsertIdempotent:
    """Test usage_daily upsert operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def store(self, temp_db):
        """Create a QuotaStore instance with temp database."""
        return QuotaStore(db_path=temp_db)

    def test_upsert_creates_new_record(self, store):
        """Upsert should create a new record if none exists."""
        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 1},
        )

        assert result is not None
        assert result.tenant_id == "tenant-1"
        assert result.project_id == "project-1"
        assert result.date == "2026-01-01"
        assert result.get_counter("jobs_enqueued") == 1

    def test_upsert_increments_existing_counter(self, store):
        """Upsert should increment existing counter values."""
        # First insert
        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 5},
        )

        # Second insert - should increment
        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 3},
        )

        assert result.get_counter("jobs_enqueued") == 8

    def test_upsert_multiple_counters(self, store):
        """Upsert should handle multiple counters correctly."""
        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 5, "reports_generated": 2},
        )

        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 3, "shares_created": 1},
        )

        assert result.get_counter("jobs_enqueued") == 8
        assert result.get_counter("reports_generated") == 2
        assert result.get_counter("shares_created") == 1

    def test_upsert_bytes_increments(self, store):
        """Upsert should increment bytes values."""
        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            bytes_increments={"artifact_bytes_written": 1024},
        )

        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            bytes_increments={"artifact_bytes_written": 2048},
        )

        assert result.get_bytes("artifact_bytes_written") == 3072

    def test_upsert_mixed_counters_and_bytes(self, store):
        """Upsert should handle both counters and bytes."""
        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 5},
            bytes_increments={"artifact_bytes_written": 1024},
        )

        assert result.get_counter("jobs_enqueued") == 5
        assert result.get_bytes("artifact_bytes_written") == 1024

    def test_upsert_different_dates_are_separate(self, store):
        """Upsert on different dates should create separate records."""
        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 5},
        )

        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-02",
            counter_increments={"jobs_enqueued": 3},
        )

        day1 = store.get_usage_daily("tenant-1", "project-1", "2026-01-01")
        day2 = store.get_usage_daily("tenant-1", "project-1", "2026-01-02")

        assert day1.get_counter("jobs_enqueued") == 5
        assert day2.get_counter("jobs_enqueued") == 3

    def test_upsert_different_projects_are_separate(self, store):
        """Upsert on different projects should create separate records."""
        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 5},
        )

        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-2",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 3},
        )

        proj1 = store.get_usage_daily("tenant-1", "project-1", "2026-01-01")
        proj2 = store.get_usage_daily("tenant-1", "project-2", "2026-01-01")

        assert proj1.get_counter("jobs_enqueued") == 5
        assert proj2.get_counter("jobs_enqueued") == 3

    def test_upsert_different_tenants_are_separate(self, store):
        """Upsert on different tenants should create separate records."""
        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 5},
        )

        store.upsert_usage_daily(
            tenant_id="tenant-2",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 3},
        )

        t1 = store.get_usage_daily("tenant-1", "project-1", "2026-01-01")
        t2 = store.get_usage_daily("tenant-2", "project-1", "2026-01-01")

        assert t1.get_counter("jobs_enqueued") == 5
        assert t2.get_counter("jobs_enqueued") == 3

    def test_upsert_empty_increments_creates_record(self, store):
        """Upsert with empty increments should still create record."""
        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
        )

        assert result is not None
        assert result.counters_json == {}
        assert result.bytes_json == {}

    def test_upsert_preserves_unrelated_counters(self, store):
        """Upsert should not affect counters not being incremented."""
        store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 5, "reports_generated": 10},
        )

        # Only increment jobs_enqueued
        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 1},
        )

        assert result.get_counter("jobs_enqueued") == 6
        assert result.get_counter("reports_generated") == 10  # Unchanged

    def test_upsert_zero_increment_still_records(self, store):
        """Upsert with zero increment should record the counter."""
        result = store.upsert_usage_daily(
            tenant_id="tenant-1",
            project_id="project-1",
            usage_date="2026-01-01",
            counter_increments={"jobs_enqueued": 0},
        )

        assert "jobs_enqueued" in result.counters_json
        assert result.get_counter("jobs_enqueued") == 0


class TestUsageDailyList:
    """Test listing and filtering usage records."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def store(self, temp_db):
        """Create a QuotaStore instance with temp database."""
        return QuotaStore(db_path=temp_db)

    @pytest.fixture
    def populated_store(self, store):
        """Create store with sample data."""
        # Tenant 1, Project 1
        store.upsert_usage_daily("t1", "p1", "2026-01-01", {"jobs": 5})
        store.upsert_usage_daily("t1", "p1", "2026-01-02", {"jobs": 3})
        store.upsert_usage_daily("t1", "p1", "2026-01-03", {"jobs": 7})

        # Tenant 1, Project 2
        store.upsert_usage_daily("t1", "p2", "2026-01-01", {"jobs": 2})
        store.upsert_usage_daily("t1", "p2", "2026-01-02", {"jobs": 4})

        # Tenant 2
        store.upsert_usage_daily("t2", "p1", "2026-01-01", {"jobs": 10})

        return store

    def test_list_by_tenant(self, populated_store):
        """List should return all records for tenant."""
        records = populated_store.list_usage_daily("t1")
        assert len(records) == 5

    def test_list_by_tenant_and_project(self, populated_store):
        """List should filter by project."""
        records = populated_store.list_usage_daily("t1", project_id="p1")
        assert len(records) == 3

    def test_list_by_date_range(self, populated_store):
        """List should filter by date range."""
        records = populated_store.list_usage_daily(
            "t1",
            from_date="2026-01-01",
            to_date="2026-01-02",
        )
        assert len(records) == 4

    def test_list_by_project_and_date_range(self, populated_store):
        """List should filter by both project and date range."""
        records = populated_store.list_usage_daily(
            "t1",
            project_id="p1",
            from_date="2026-01-01",
            to_date="2026-01-02",
        )
        assert len(records) == 2

    def test_list_ordered_by_date_descending(self, populated_store):
        """List should return records ordered by date descending."""
        records = populated_store.list_usage_daily("t1", project_id="p1")
        dates = [r.date for r in records]
        assert dates == ["2026-01-03", "2026-01-02", "2026-01-01"]


class TestUsageDailyAggregate:
    """Test aggregation of usage records."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def store(self, temp_db):
        """Create a QuotaStore instance with temp database."""
        return QuotaStore(db_path=temp_db)

    @pytest.fixture
    def populated_store(self, store):
        """Create store with sample data."""
        store.upsert_usage_daily("t1", "p1", "2026-01-01", {"jobs": 5, "reports": 2}, {"bytes": 100})
        store.upsert_usage_daily("t1", "p1", "2026-01-02", {"jobs": 3, "reports": 1}, {"bytes": 200})
        store.upsert_usage_daily("t1", "p1", "2026-01-03", {"jobs": 7, "shares": 2}, {"bytes": 150})
        return store

    def test_aggregate_sums_counters(self, populated_store):
        """Aggregate should sum all counter values."""
        result = populated_store.aggregate_usage_daily("t1", project_id="p1")

        assert result["counters"]["jobs"] == 15  # 5 + 3 + 7
        assert result["counters"]["reports"] == 3  # 2 + 1
        assert result["counters"]["shares"] == 2

    def test_aggregate_sums_bytes(self, populated_store):
        """Aggregate should sum all bytes values."""
        result = populated_store.aggregate_usage_daily("t1", project_id="p1")

        assert result["bytes"]["bytes"] == 450  # 100 + 200 + 150

    def test_aggregate_counts_days(self, populated_store):
        """Aggregate should count unique days."""
        result = populated_store.aggregate_usage_daily("t1", project_id="p1")

        assert result["days_count"] == 3

    def test_aggregate_with_date_range(self, populated_store):
        """Aggregate should respect date range filter."""
        result = populated_store.aggregate_usage_daily(
            "t1",
            project_id="p1",
            from_date="2026-01-01",
            to_date="2026-01-02",
        )

        assert result["counters"]["jobs"] == 8  # 5 + 3
        assert result["days_count"] == 2

    def test_aggregate_empty_returns_zeros(self, store):
        """Aggregate with no data should return empty counters."""
        result = store.aggregate_usage_daily("nonexistent")

        assert result["counters"] == {}
        assert result["bytes"] == {}
        assert result["days_count"] == 0


class TestTenantSettingsCRUD:
    """Test tenant settings CRUD operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def store(self, temp_db):
        """Create a QuotaStore instance with temp database."""
        return QuotaStore(db_path=temp_db)

    def test_upsert_creates_with_default_plan(self, store):
        """Upsert should create settings with default plan."""
        result = store.upsert_tenant_settings("tenant-1")

        assert result is not None
        assert result.tenant_id == "tenant-1"
        assert result.plan_id == "free"  # Default plan
        assert result.billing_status == "active"

    def test_upsert_creates_with_specified_plan(self, store):
        """Upsert should use specified plan."""
        result = store.upsert_tenant_settings("tenant-1", plan_id="pro")

        assert result.plan_id == "pro"

    def test_upsert_updates_existing(self, store):
        """Upsert should update existing settings."""
        store.upsert_tenant_settings("tenant-1", plan_id="free")
        result = store.upsert_tenant_settings("tenant-1", plan_id="pro")

        assert result.plan_id == "pro"

    def test_upsert_updates_billing_status(self, store):
        """Upsert should update billing status."""
        store.upsert_tenant_settings("tenant-1")
        result = store.upsert_tenant_settings("tenant-1", billing_status="suspended")

        assert result.billing_status == "suspended"

    def test_upsert_sets_grace_mode(self, store):
        """Upsert should set grace mode date."""
        store.upsert_tenant_settings("tenant-1")
        result = store.upsert_tenant_settings(
            "tenant-1",
            billing_status="grace",
            grace_mode_until="2026-02-01T00:00:00Z",
        )

        assert result.billing_status == "grace"
        assert result.grace_mode_until == "2026-02-01T00:00:00Z"

    def test_get_nonexistent_returns_none(self, store):
        """Get should return None for nonexistent tenant."""
        result = store.get_tenant_settings("nonexistent")
        assert result is None


class TestProjectQuotasCRUD:
    """Test project quotas CRUD operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def store(self, temp_db):
        """Create a QuotaStore instance with temp database."""
        return QuotaStore(db_path=temp_db)

    def test_upsert_creates_new_quota(self, store):
        """Upsert should create new project quota."""
        result = store.upsert_project_quota(
            "tenant-1",
            "project-1",
            {"jobs_per_day": 200},
        )

        assert result is not None
        assert result.get_override("jobs_per_day") == 200

    def test_upsert_merges_overrides(self, store):
        """Upsert should merge new overrides with existing."""
        store.upsert_project_quota("tenant-1", "project-1", {"jobs_per_day": 200})
        result = store.upsert_project_quota(
            "tenant-1",
            "project-1",
            {"reports_per_day": 100},
        )

        assert result.get_override("jobs_per_day") == 200
        assert result.get_override("reports_per_day") == 100

    def test_upsert_overwrites_same_key(self, store):
        """Upsert should overwrite same key with new value."""
        store.upsert_project_quota("tenant-1", "project-1", {"jobs_per_day": 200})
        result = store.upsert_project_quota(
            "tenant-1",
            "project-1",
            {"jobs_per_day": 300},
        )

        assert result.get_override("jobs_per_day") == 300

    def test_list_by_tenant(self, store):
        """List should return all quotas for tenant."""
        store.upsert_project_quota("tenant-1", "project-1", {"jobs_per_day": 100})
        store.upsert_project_quota("tenant-1", "project-2", {"jobs_per_day": 200})
        store.upsert_project_quota("tenant-2", "project-1", {"jobs_per_day": 300})

        quotas = store.list_project_quotas("tenant-1")

        assert len(quotas) == 2
        project_ids = {q.project_id for q in quotas}
        assert project_ids == {"project-1", "project-2"}

    def test_get_nonexistent_returns_none(self, store):
        """Get should return None for nonexistent quota."""
        result = store.get_project_quota("tenant-1", "nonexistent")
        assert result is None
