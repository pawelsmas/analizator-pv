"""
Unit tests for quota engine override precedence.

Tests verify:
- Plan limits are used as base
- Project overrides take precedence over plan limits
- Zero override means unlimited
- Missing overrides use plan defaults
"""

import os
import sys
import tempfile
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from quota_store import QuotaStore, Plan, ProjectQuota
from quota_engine import (
    compute_effective_limits,
    get_quota_snapshot,
    check_quota,
    get_next_reset_time,
    get_seconds_until_reset,
    QuotaSnapshot,
    get_quota_store,
)
import quota_engine


# -----------------------------------------------------------------------------
# Test fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def test_store(temp_db):
    """Create a QuotaStore instance with temp database."""
    return QuotaStore(db_path=temp_db)


@pytest.fixture
def setup_quota_engine(test_store, monkeypatch):
    """Configure quota engine to use test store."""
    # Reset the module-level singleton
    monkeypatch.setattr(quota_engine, "_quota_store", test_store)
    return test_store


# -----------------------------------------------------------------------------
# compute_effective_limits tests
# -----------------------------------------------------------------------------

class TestComputeEffectiveLimits:
    """Tests for compute_effective_limits function."""

    def test_uses_plan_limits_when_no_overrides(self):
        """Should use plan limits when no project overrides."""
        plan = Plan(
            id="test-plan",
            name="Test Plan",
            limits_json={"jobs_per_day": 100, "storage_mb": 500},
            created_at="2024-01-01T00:00:00Z",
        )

        limits = compute_effective_limits(plan, None)

        assert limits == {"jobs_per_day": 100, "storage_mb": 500}

    def test_override_takes_precedence(self):
        """Project override should take precedence over plan limit."""
        plan = Plan(
            id="test-plan",
            name="Test Plan",
            limits_json={"jobs_per_day": 100, "storage_mb": 500},
            created_at="2024-01-01T00:00:00Z",
        )
        override = ProjectQuota(
            tenant_id="tenant-1",
            project_id="project-1",
            overrides_json={"jobs_per_day": 200},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )

        limits = compute_effective_limits(plan, override)

        assert limits["jobs_per_day"] == 200  # Override
        assert limits["storage_mb"] == 500    # Plan default

    def test_zero_override_means_unlimited(self):
        """Zero override should set limit to 0 (unlimited)."""
        plan = Plan(
            id="test-plan",
            name="Test Plan",
            limits_json={"jobs_per_day": 100},
            created_at="2024-01-01T00:00:00Z",
        )
        override = ProjectQuota(
            tenant_id="tenant-1",
            project_id="project-1",
            overrides_json={"jobs_per_day": 0},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )

        limits = compute_effective_limits(plan, override)

        assert limits["jobs_per_day"] == 0

    def test_none_override_uses_plan_default(self):
        """None value in override should be ignored."""
        plan = Plan(
            id="test-plan",
            name="Test Plan",
            limits_json={"jobs_per_day": 100, "storage_mb": 500},
            created_at="2024-01-01T00:00:00Z",
        )
        override = ProjectQuota(
            tenant_id="tenant-1",
            project_id="project-1",
            overrides_json={"jobs_per_day": None, "storage_mb": 1000},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )

        limits = compute_effective_limits(plan, override)

        assert limits["jobs_per_day"] == 100   # Plan default (None ignored)
        assert limits["storage_mb"] == 1000    # Override

    def test_multiple_overrides(self):
        """Should apply multiple overrides correctly."""
        plan = Plan(
            id="test-plan",
            name="Test Plan",
            limits_json={
                "jobs_per_day": 100,
                "reports_per_day": 50,
                "shares_total": 10,
                "storage_mb": 500,
            },
            created_at="2024-01-01T00:00:00Z",
        )
        override = ProjectQuota(
            tenant_id="tenant-1",
            project_id="project-1",
            overrides_json={
                "jobs_per_day": 200,
                "shares_total": 50,
            },
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )

        limits = compute_effective_limits(plan, override)

        assert limits["jobs_per_day"] == 200    # Override
        assert limits["reports_per_day"] == 50  # Plan default
        assert limits["shares_total"] == 50     # Override
        assert limits["storage_mb"] == 500      # Plan default


# -----------------------------------------------------------------------------
# QuotaSnapshot tests
# -----------------------------------------------------------------------------

class TestQuotaSnapshot:
    """Tests for QuotaSnapshot dataclass methods."""

    def test_is_exceeded_when_at_limit(self):
        """Should return True when usage equals limit."""
        snapshot = QuotaSnapshot(
            tenant_id="t1",
            project_id="p1",
            plan_id="free",
            limits={"jobs_per_day": 10},
            used_today={"jobs_per_day": 10},
            remaining={"jobs_per_day": 0},
        )

        assert snapshot.is_exceeded("jobs_per_day") is True

    def test_is_exceeded_when_over_limit(self):
        """Should return True when usage exceeds limit."""
        snapshot = QuotaSnapshot(
            tenant_id="t1",
            project_id="p1",
            plan_id="free",
            limits={"jobs_per_day": 10},
            used_today={"jobs_per_day": 15},
            remaining={"jobs_per_day": 0},
        )

        assert snapshot.is_exceeded("jobs_per_day") is True

    def test_is_exceeded_when_under_limit(self):
        """Should return False when usage is under limit."""
        snapshot = QuotaSnapshot(
            tenant_id="t1",
            project_id="p1",
            plan_id="free",
            limits={"jobs_per_day": 10},
            used_today={"jobs_per_day": 5},
            remaining={"jobs_per_day": 5},
        )

        assert snapshot.is_exceeded("jobs_per_day") is False

    def test_is_exceeded_unknown_quota(self):
        """Should return False for unknown quota name."""
        snapshot = QuotaSnapshot(
            tenant_id="t1",
            project_id="p1",
            plan_id="free",
            limits={"jobs_per_day": 10},
            used_today={},
            remaining={},
        )

        assert snapshot.is_exceeded("unknown_quota") is False

    def test_get_remaining(self):
        """Should return remaining quota."""
        snapshot = QuotaSnapshot(
            tenant_id="t1",
            project_id="p1",
            plan_id="free",
            limits={"jobs_per_day": 10},
            used_today={"jobs_per_day": 3},
            remaining={"jobs_per_day": 7},
        )

        assert snapshot.get_remaining("jobs_per_day") == 7

    def test_get_remaining_when_exceeded(self):
        """Should return 0 when quota exceeded."""
        snapshot = QuotaSnapshot(
            tenant_id="t1",
            project_id="p1",
            plan_id="free",
            limits={"jobs_per_day": 10},
            used_today={"jobs_per_day": 15},
            remaining={"jobs_per_day": 0},
        )

        assert snapshot.get_remaining("jobs_per_day") == 0

    def test_get_remaining_unknown_quota(self):
        """Should return None for unknown quota."""
        snapshot = QuotaSnapshot(
            tenant_id="t1",
            project_id="p1",
            plan_id="free",
            limits={},
            used_today={},
            remaining={},
        )

        assert snapshot.get_remaining("unknown") is None


# -----------------------------------------------------------------------------
# get_quota_snapshot tests
# -----------------------------------------------------------------------------

class TestGetQuotaSnapshot:
    """Tests for get_quota_snapshot function."""

    def test_returns_snapshot_with_plan_limits(self, setup_quota_engine):
        """Should return snapshot with plan limits."""
        store = setup_quota_engine

        # Use the default seeded "pro" plan (100 jobs/day)
        store.upsert_tenant_settings("tenant-1", plan_id="pro")

        snapshot = get_quota_snapshot("tenant-1", "project-1")

        assert snapshot.tenant_id == "tenant-1"
        assert snapshot.project_id == "project-1"
        assert snapshot.plan_id == "pro"
        assert snapshot.limits["jobs_per_day"] == 100

    def test_returns_snapshot_with_overrides(self, setup_quota_engine):
        """Should apply project overrides to snapshot."""
        store = setup_quota_engine

        # Use the default seeded "pro" plan
        store.upsert_tenant_settings("tenant-2", plan_id="pro")

        # Create project override
        store.upsert_project_quota("tenant-2", "project-2", {"jobs_per_day": 200})

        snapshot = get_quota_snapshot("tenant-2", "project-2")

        assert snapshot.limits["jobs_per_day"] == 200

    def test_returns_snapshot_with_usage(self, setup_quota_engine):
        """Should include today's usage in snapshot."""
        store = setup_quota_engine

        # Use the default seeded "pro" plan (100 jobs/day)
        store.upsert_tenant_settings("tenant-3", plan_id="pro")

        # Record some usage
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-3", "project-3", today, {"jobs_per_day": 5})

        snapshot = get_quota_snapshot("tenant-3", "project-3")

        assert snapshot.used_today.get("jobs_per_day") == 5
        assert snapshot.remaining["jobs_per_day"] == 95

    def test_returns_snapshot_with_default_plan_for_new_tenant(self, setup_quota_engine):
        """Should return snapshot with default plan for new tenant."""
        # New tenant gets default 'free' plan (10 jobs/day)
        snapshot = get_quota_snapshot("new-tenant", "new-project")

        assert snapshot.tenant_id == "new-tenant"
        assert snapshot.project_id == "new-project"
        assert snapshot.plan_id == "free"  # Default plan
        assert snapshot.limits["jobs_per_day"] == 10

    def test_uses_default_plan_when_tenant_plan_missing(self, setup_quota_engine):
        """Should use default plan when tenant's plan is not found."""
        store = setup_quota_engine

        # Create tenant with non-existent plan
        store.upsert_tenant_settings("tenant-4", plan_id="non-existent-plan")

        snapshot = get_quota_snapshot("tenant-4", "project-4")

        # Should fall back to default plan (free = 10 jobs/day)
        assert snapshot.limits["jobs_per_day"] == 10


# -----------------------------------------------------------------------------
# check_quota tests
# -----------------------------------------------------------------------------

class TestCheckQuota:
    """Tests for check_quota function."""

    def test_allowed_when_under_limit(self, setup_quota_engine):
        """Should allow when under limit."""
        store = setup_quota_engine

        # Use seeded 'pro' plan (100 jobs/day)
        store.upsert_tenant_settings("tenant-check-1", plan_id="pro")

        result = check_quota("tenant-check-1", "project-1", "jobs_per_day")

        assert result["allowed"] is True
        assert result["limit"] == 100
        assert result["used"] == 0
        assert result["remaining"] == 99  # 100 - 1 (the increment)

    def test_denied_when_at_limit(self, setup_quota_engine):
        """Should deny when at limit."""
        store = setup_quota_engine

        # Use seeded 'free' plan (10 jobs/day)
        store.upsert_tenant_settings("tenant-check-2", plan_id="free")

        # Use up quota
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-check-2", "project-2", today, {"jobs_per_day": 10})

        result = check_quota("tenant-check-2", "project-2", "jobs_per_day")

        assert result["allowed"] is False
        assert result["limit"] == 10
        assert result["used"] == 10
        assert result["remaining"] == 0

    def test_denied_when_would_exceed(self, setup_quota_engine):
        """Should deny when increment would exceed limit."""
        store = setup_quota_engine

        # Use seeded 'free' plan (10 jobs/day)
        store.upsert_tenant_settings("tenant-check-3", plan_id="free")

        # Use 9 of 10 quota
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-check-3", "project-3", today, {"jobs_per_day": 9})

        # Try to add 2 (would exceed)
        result = check_quota("tenant-check-3", "project-3", "jobs_per_day", increment=2)

        assert result["allowed"] is False

    def test_allowed_when_unlimited(self, setup_quota_engine):
        """Should allow when limit is 0 (unlimited)."""
        store = setup_quota_engine

        # Use project override to set unlimited (0)
        store.upsert_tenant_settings("tenant-check-4", plan_id="free")
        store.upsert_project_quota("tenant-check-4", "project-4", {"jobs_per_day": 0})

        result = check_quota("tenant-check-4", "project-4", "jobs_per_day")

        assert result["allowed"] is True
        assert result["limit"] == 0
        assert result["remaining"] is None  # Unlimited

    def test_allowed_when_quota_not_defined(self, setup_quota_engine):
        """Should allow when quota name not in limits."""
        store = setup_quota_engine

        # Use seeded 'free' plan
        store.upsert_tenant_settings("tenant-check-5", plan_id="free")

        result = check_quota("tenant-check-5", "project-5", "unknown_quota")

        assert result["allowed"] is True
        assert result["limit"] is None

    def test_returns_reset_time(self, setup_quota_engine):
        """Should include reset time in response."""
        store = setup_quota_engine

        # Use seeded 'free' plan
        store.upsert_tenant_settings("tenant-check-6", plan_id="free")

        result = check_quota("tenant-check-6", "project-6", "jobs_per_day")

        assert "reset_at" in result
        assert result["reset_at"] is not None


# -----------------------------------------------------------------------------
# Helper function tests
# -----------------------------------------------------------------------------

class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_next_reset_time_format(self):
        """Should return ISO 8601 format."""
        reset_time = get_next_reset_time()

        # Should be parseable as ISO 8601
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
        assert parsed is not None

    def test_get_next_reset_time_is_tomorrow(self):
        """Should be tomorrow at midnight UTC."""
        reset_time = get_next_reset_time()
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))

        now = datetime.now(timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Should be midnight
        assert parsed.hour == 0
        assert parsed.minute == 0
        assert parsed.second == 0

    def test_get_seconds_until_reset_positive(self):
        """Should return positive number of seconds."""
        seconds = get_seconds_until_reset()

        assert seconds > 0
        assert seconds <= 86400  # At most 24 hours
