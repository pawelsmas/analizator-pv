"""
Unit tests for quota tables existence and schema.

Tests verify that all required tables are created with proper schema.
"""

import json
import os
import sqlite3
import tempfile
import pytest
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from quota_store import QuotaStore, Plan, TenantSettings, ProjectQuota, UsageDaily, DEFAULT_PLANS


class TestQuotaTablesExist:
    """Test that all quota tables are created properly."""

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

    def test_tables_exist_returns_all_true(self, store):
        """All quota tables should exist after initialization."""
        result = store.tables_exist()
        assert result["plans"] is True
        assert result["tenant_settings"] is True
        assert result["project_quotas"] is True
        assert result["usage_daily"] is True

    def test_plans_table_has_correct_columns(self, store):
        """Plans table should have all required columns."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(plans)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required = {"id", "name", "limits_json", "created_at", "is_default"}
        assert required.issubset(columns)

    def test_tenant_settings_table_has_correct_columns(self, store):
        """Tenant settings table should have all required columns."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(tenant_settings)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required = {"tenant_id", "plan_id", "billing_status", "grace_mode_until", "created_at", "updated_at"}
        assert required.issubset(columns)

    def test_project_quotas_table_has_correct_columns(self, store):
        """Project quotas table should have all required columns."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(project_quotas)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required = {"tenant_id", "project_id", "overrides_json", "created_at", "updated_at"}
        assert required.issubset(columns)

    def test_usage_daily_table_has_correct_columns(self, store):
        """Usage daily table should have all required columns."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(usage_daily)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required = {"tenant_id", "project_id", "date", "counters_json", "bytes_json", "created_at"}
        assert required.issubset(columns)

    def test_plans_table_has_primary_key(self, store):
        """Plans table should have id as primary key."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(plans)")
        rows = cursor.fetchall()
        pk_columns = [row[1] for row in rows if row[5] == 1]
        conn.close()

        assert "id" in pk_columns

    def test_tenant_settings_table_has_primary_key(self, store):
        """Tenant settings table should have tenant_id as primary key."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(tenant_settings)")
        rows = cursor.fetchall()
        pk_columns = [row[1] for row in rows if row[5] == 1]
        conn.close()

        assert "tenant_id" in pk_columns

    def test_project_quotas_table_has_composite_primary_key(self, store):
        """Project quotas table should have composite primary key."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(project_quotas)")
        rows = cursor.fetchall()
        pk_columns = [row[1] for row in rows if row[5] > 0]
        conn.close()

        assert "tenant_id" in pk_columns
        assert "project_id" in pk_columns

    def test_usage_daily_table_has_composite_primary_key(self, store):
        """Usage daily table should have composite primary key (tenant, project, date)."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("PRAGMA table_info(usage_daily)")
        rows = cursor.fetchall()
        pk_columns = [row[1] for row in rows if row[5] > 0]
        conn.close()

        assert "tenant_id" in pk_columns
        assert "project_id" in pk_columns
        assert "date" in pk_columns

    def test_default_plans_are_seeded(self, store):
        """Default plans should be seeded on initialization."""
        plans = store.list_plans()
        plan_ids = {p.id for p in plans}

        assert "free" in plan_ids
        assert "pro" in plan_ids
        assert "enterprise" in plan_ids

    def test_free_plan_is_default(self, store):
        """Free plan should be marked as default."""
        default_plan = store.get_default_plan()
        assert default_plan is not None
        assert default_plan.id == "free"
        assert default_plan.is_default is True

    def test_plans_have_correct_limits(self, store):
        """Plans should have correct limit values."""
        free_plan = store.get_plan("free")
        assert free_plan is not None
        assert free_plan.get_limit("jobs_per_day") == 10
        assert free_plan.get_limit("reports_per_day") == 5
        assert free_plan.get_limit("shares_total") == 10
        assert free_plan.get_limit("storage_mb") == 100

        pro_plan = store.get_plan("pro")
        assert pro_plan is not None
        assert pro_plan.get_limit("jobs_per_day") == 100
        assert pro_plan.get_limit("storage_mb") == 1000

        enterprise_plan = store.get_plan("enterprise")
        assert enterprise_plan is not None
        assert enterprise_plan.get_limit("jobs_per_day") == 1000

    def test_indexes_exist(self, store):
        """Required indexes should exist."""
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()

        # Check for key indexes (some may have auto-generated names for PK)
        assert "idx_tenant_settings_plan_id" in indexes
        assert "idx_project_quotas_tenant_id" in indexes
        assert "idx_usage_daily_tenant_id" in indexes
        assert "idx_usage_daily_date" in indexes

    def test_reinitialize_does_not_duplicate_plans(self, temp_db):
        """Re-initializing store should not duplicate plans."""
        store1 = QuotaStore(db_path=temp_db)
        plans_count_1 = len(store1.list_plans())

        # Create another store instance (simulates restart)
        store2 = QuotaStore(db_path=temp_db)
        plans_count_2 = len(store2.list_plans())

        assert plans_count_1 == plans_count_2 == 3


class TestPlanDataClass:
    """Tests for Plan dataclass."""

    def test_plan_get_limit_existing(self):
        """get_limit returns correct value for existing limit."""
        plan = Plan(
            id="test",
            name="Test",
            limits_json={"jobs_per_day": 50},
            created_at="2026-01-01T00:00:00Z",
        )
        assert plan.get_limit("jobs_per_day") == 50

    def test_plan_get_limit_missing(self):
        """get_limit returns None for missing limit."""
        plan = Plan(
            id="test",
            name="Test",
            limits_json={"jobs_per_day": 50},
            created_at="2026-01-01T00:00:00Z",
        )
        assert plan.get_limit("nonexistent") is None


class TestTenantSettingsDataClass:
    """Tests for TenantSettings dataclass."""

    def test_tenant_settings_creation(self):
        """TenantSettings can be created with all fields."""
        settings = TenantSettings(
            tenant_id="tenant-1",
            plan_id="pro",
            billing_status="active",
            grace_mode_until=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert settings.tenant_id == "tenant-1"
        assert settings.billing_status == "active"


class TestProjectQuotaDataClass:
    """Tests for ProjectQuota dataclass."""

    def test_project_quota_get_override_existing(self):
        """get_override returns correct value for existing override."""
        quota = ProjectQuota(
            tenant_id="tenant-1",
            project_id="project-1",
            overrides_json={"jobs_per_day": 200},
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert quota.get_override("jobs_per_day") == 200

    def test_project_quota_get_override_missing(self):
        """get_override returns None for missing override."""
        quota = ProjectQuota(
            tenant_id="tenant-1",
            project_id="project-1",
            overrides_json={},
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert quota.get_override("jobs_per_day") is None


class TestUsageDailyDataClass:
    """Tests for UsageDaily dataclass."""

    def test_usage_daily_get_counter_existing(self):
        """get_counter returns correct value for existing counter."""
        usage = UsageDaily(
            tenant_id="tenant-1",
            project_id="project-1",
            date="2026-01-01",
            counters_json={"jobs_enqueued": 5},
        )
        assert usage.get_counter("jobs_enqueued") == 5

    def test_usage_daily_get_counter_missing_returns_zero(self):
        """get_counter returns 0 for missing counter."""
        usage = UsageDaily(
            tenant_id="tenant-1",
            project_id="project-1",
            date="2026-01-01",
            counters_json={},
        )
        assert usage.get_counter("jobs_enqueued") == 0

    def test_usage_daily_get_bytes_existing(self):
        """get_bytes returns correct value for existing bytes counter."""
        usage = UsageDaily(
            tenant_id="tenant-1",
            project_id="project-1",
            date="2026-01-01",
            bytes_json={"artifact_bytes_written": 1024},
        )
        assert usage.get_bytes("artifact_bytes_written") == 1024

    def test_usage_daily_get_bytes_missing_returns_zero(self):
        """get_bytes returns 0 for missing bytes counter."""
        usage = UsageDaily(
            tenant_id="tenant-1",
            project_id="project-1",
            date="2026-01-01",
            bytes_json={},
        )
        assert usage.get_bytes("artifact_bytes_written") == 0
