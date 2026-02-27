"""
Unit tests for quota enforcement middleware.

Tests verify:
- check_and_enforce raises QuotaExceededError when quota exceeded
- 429 response includes Retry-After header
- Convenience functions work correctly
- QuotaExceededError has correct attributes
"""

import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from quota_store import QuotaStore
from quota_enforcement import (
    QuotaExceededError,
    check_and_enforce,
    enforce_jobs_quota,
    enforce_reports_quota,
    enforce_shares_quota,
    enforce_storage_quota,
    QuotaEnforcer,
    QUOTA_EXCEEDED_CODE,
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
    monkeypatch.setattr(quota_engine, "_quota_store", test_store)
    return test_store


# -----------------------------------------------------------------------------
# QuotaExceededError tests
# -----------------------------------------------------------------------------

class TestQuotaExceededError:
    """Tests for QuotaExceededError exception."""

    def test_has_429_status_code(self):
        """Should have 429 status code."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert error.status_code == 429

    def test_has_retry_after_header(self):
        """Should include Retry-After header."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert "Retry-After" in error.headers
        assert error.headers["Retry-After"] == "3600"

    def test_has_quota_name_in_detail(self):
        """Should include quota name in detail."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert error.detail["quota_name"] == "jobs_per_day"

    def test_has_limit_in_detail(self):
        """Should include limit in detail."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert error.detail["limit"] == 10

    def test_has_used_in_detail(self):
        """Should include used count in detail."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert error.detail["used"] == 10

    def test_has_retry_after_in_detail(self):
        """Should include retry_after_seconds in detail."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert error.detail["retry_after_seconds"] == 3600

    def test_has_quota_exceeded_code(self):
        """Should have QUOTA_EXCEEDED error code."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert error.detail["code"] == QUOTA_EXCEEDED_CODE

    def test_has_message_in_detail(self):
        """Should include message in detail."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
        )

        assert "message" in error.detail
        assert "jobs_per_day" in error.detail["message"]

    def test_custom_message(self):
        """Should accept custom message."""
        error = QuotaExceededError(
            quota_name="jobs_per_day",
            limit=10,
            used=10,
            retry_after=3600,
            message="Custom error message",
        )

        assert error.detail["message"] == "Custom error message"


# -----------------------------------------------------------------------------
# check_and_enforce tests
# -----------------------------------------------------------------------------

class TestCheckAndEnforce:
    """Tests for check_and_enforce function."""

    def test_allows_when_under_limit(self, setup_quota_engine):
        """Should not raise when under limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-1", plan_id="pro")

        # Should not raise
        result = check_and_enforce("tenant-1", "project-1", "jobs_per_day")

        assert result["allowed"] is True

    def test_raises_when_at_limit(self, setup_quota_engine):
        """Should raise QuotaExceededError when at limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-2", plan_id="free")

        # Use up quota (free plan = 10 jobs/day)
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-2", "project-2", today, {"jobs_per_day": 10})

        with pytest.raises(QuotaExceededError) as exc_info:
            check_and_enforce("tenant-2", "project-2", "jobs_per_day")

        assert exc_info.value.status_code == 429
        assert exc_info.value.limit == 10
        assert exc_info.value.used == 10

    def test_raises_when_would_exceed(self, setup_quota_engine):
        """Should raise when increment would exceed."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-3", plan_id="free")

        # Use 9 of 10 quota
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-3", "project-3", today, {"jobs_per_day": 9})

        # Try to add 2 (would exceed)
        with pytest.raises(QuotaExceededError):
            check_and_enforce("tenant-3", "project-3", "jobs_per_day", increment=2)

    def test_allows_when_unlimited(self, setup_quota_engine):
        """Should not raise when quota is unlimited (0)."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-4", plan_id="free")
        store.upsert_project_quota("tenant-4", "project-4", {"jobs_per_day": 0})

        # Should not raise - unlimited
        result = check_and_enforce("tenant-4", "project-4", "jobs_per_day")

        assert result["allowed"] is True

    def test_retry_after_is_positive(self, setup_quota_engine):
        """Retry-After should be positive number of seconds."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-5", plan_id="free")

        today = store.get_today_date()
        store.upsert_usage_daily("tenant-5", "project-5", today, {"jobs_per_day": 10})

        with pytest.raises(QuotaExceededError) as exc_info:
            check_and_enforce("tenant-5", "project-5", "jobs_per_day")

        assert exc_info.value.retry_after > 0
        assert exc_info.value.retry_after <= 86400  # At most 24 hours


# -----------------------------------------------------------------------------
# Convenience function tests
# -----------------------------------------------------------------------------

class TestConvenienceFunctions:
    """Tests for convenience enforcement functions."""

    def test_enforce_jobs_quota_allows(self, setup_quota_engine):
        """enforce_jobs_quota should allow when under limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-jobs", plan_id="pro")

        result = enforce_jobs_quota("tenant-jobs", "project-1")

        assert result["allowed"] is True

    def test_enforce_jobs_quota_denies(self, setup_quota_engine):
        """enforce_jobs_quota should deny when at limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-jobs-deny", plan_id="free")

        today = store.get_today_date()
        store.upsert_usage_daily("tenant-jobs-deny", "project-1", today, {"jobs_per_day": 10})

        with pytest.raises(QuotaExceededError):
            enforce_jobs_quota("tenant-jobs-deny", "project-1")

    def test_enforce_reports_quota_allows(self, setup_quota_engine):
        """enforce_reports_quota should allow when under limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-reports", plan_id="pro")

        result = enforce_reports_quota("tenant-reports", "project-1")

        assert result["allowed"] is True

    def test_enforce_reports_quota_denies(self, setup_quota_engine):
        """enforce_reports_quota should deny when at limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-reports-deny", plan_id="free")

        today = store.get_today_date()
        store.upsert_usage_daily("tenant-reports-deny", "project-1", today, {"reports_per_day": 5})

        with pytest.raises(QuotaExceededError):
            enforce_reports_quota("tenant-reports-deny", "project-1")

    def test_enforce_shares_quota_allows(self, setup_quota_engine):
        """enforce_shares_quota should allow when under limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-shares", plan_id="pro")

        result = enforce_shares_quota("tenant-shares", "project-1")

        assert result["allowed"] is True

    def test_enforce_storage_quota_allows(self, setup_quota_engine):
        """enforce_storage_quota should allow when under limit."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-storage", plan_id="pro")

        result = enforce_storage_quota("tenant-storage", "project-1", 1024 * 1024)

        assert result["allowed"] is True


# -----------------------------------------------------------------------------
# QuotaEnforcer dependency tests
# -----------------------------------------------------------------------------

class TestQuotaEnforcer:
    """Tests for QuotaEnforcer dependency."""

    def test_creates_with_quota_name(self):
        """Should create with quota name."""
        enforcer = QuotaEnforcer("jobs_per_day")

        assert enforcer.quota_name == "jobs_per_day"
        assert enforcer.increment == 1

    def test_creates_with_custom_increment(self):
        """Should accept custom increment."""
        enforcer = QuotaEnforcer("jobs_per_day", increment=5)

        assert enforcer.increment == 5

    @pytest.mark.asyncio
    async def test_raises_without_ids(self):
        """Should raise ValueError without tenant/project IDs."""
        enforcer = QuotaEnforcer("jobs_per_day")

        with pytest.raises(ValueError):
            await enforcer()

    @pytest.mark.asyncio
    async def test_allows_with_explicit_ids(self, setup_quota_engine):
        """Should work with explicit tenant/project IDs."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-enforcer", plan_id="pro")

        enforcer = QuotaEnforcer("jobs_per_day")
        result = await enforcer(tenant_id="tenant-enforcer", project_id="project-1")

        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_allows_with_auth_context(self, setup_quota_engine):
        """Should work with auth context object."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-auth", plan_id="pro")

        # Create mock auth context
        auth = MagicMock()
        auth.tenant_id = "tenant-auth"
        auth.project_id = "project-1"

        enforcer = QuotaEnforcer("jobs_per_day")
        result = await enforcer(auth=auth)

        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_denies_when_exceeded(self, setup_quota_engine):
        """Should raise QuotaExceededError when exceeded."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-enforcer-deny", plan_id="free")

        today = store.get_today_date()
        store.upsert_usage_daily("tenant-enforcer-deny", "project-1", today, {"jobs_per_day": 10})

        enforcer = QuotaEnforcer("jobs_per_day")

        with pytest.raises(QuotaExceededError):
            await enforcer(tenant_id="tenant-enforcer-deny", project_id="project-1")


# -----------------------------------------------------------------------------
# Integration tests
# -----------------------------------------------------------------------------

class TestEnforcementIntegration:
    """Integration tests for enforcement."""

    def test_respects_project_override(self, setup_quota_engine):
        """Should respect project-level override."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-override", plan_id="free")

        # Override to allow 100 jobs instead of 10
        store.upsert_project_quota("tenant-override", "project-1", {"jobs_per_day": 100})

        # Use 50 jobs
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-override", "project-1", today, {"jobs_per_day": 50})

        # Should still be allowed (50 < 100)
        result = check_and_enforce("tenant-override", "project-1", "jobs_per_day")

        assert result["allowed"] is True

    def test_different_quotas_independent(self, setup_quota_engine):
        """Different quota types should be independent."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-independent", plan_id="free")

        # Max out jobs quota
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-independent", "project-1", today, {"jobs_per_day": 10})

        # Jobs should be denied
        with pytest.raises(QuotaExceededError):
            check_and_enforce("tenant-independent", "project-1", "jobs_per_day")

        # But reports should still be allowed
        result = check_and_enforce("tenant-independent", "project-1", "reports_per_day")
        assert result["allowed"] is True

    def test_batch_increment_check(self, setup_quota_engine):
        """Should check batch operations correctly."""
        store = setup_quota_engine
        store.upsert_tenant_settings("tenant-batch", plan_id="free")

        # Use 8 of 10 quota
        today = store.get_today_date()
        store.upsert_usage_daily("tenant-batch", "project-1", today, {"jobs_per_day": 8})

        # Single increment should work
        result = check_and_enforce("tenant-batch", "project-1", "jobs_per_day", increment=1)
        assert result["allowed"] is True

        # Batch of 3 should fail (8 + 3 = 11 > 10)
        with pytest.raises(QuotaExceededError):
            check_and_enforce("tenant-batch", "project-1", "jobs_per_day", increment=3)
