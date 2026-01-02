"""
Unit tests for legal hold matcher and guards (v4.3.0 PR3).

Tests:
- LegalHoldMatcher matching logic
- HoldViolationError
- purge_guard context manager
- list_affected_resources
- get_hold_summary
"""

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_store import ComplianceStore
from legal_hold_helper import (
    LegalHoldMatcher,
    HoldMatch,
    HoldScope,
    HoldViolationError,
    ResourceRef,
    check_resource_held,
    purge_guard,
    list_affected_resources,
    get_hold_summary,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def store(temp_db):
    """Create a ComplianceStore with temporary database."""
    return ComplianceStore(db_path=temp_db)


@pytest.fixture
def matcher(store):
    """Create a LegalHoldMatcher."""
    return LegalHoldMatcher(store)


class TestHoldMatch:
    """Tests for HoldMatch model."""

    def test_empty_match(self):
        """Test empty match (not held)."""
        match = HoldMatch()
        assert match.is_held is False
        assert match.holds == []
        assert match.hold_ids == []
        assert match.reasons == []
        assert match.scope is None

    def test_match_to_dict(self):
        """Test converting match to dict."""
        match = HoldMatch(
            is_held=True,
            hold_ids=["h1", "h2"],
            reasons=["Reason 1", "Reason 2"],
            scope=HoldScope.PROJECT,
        )
        d = match.to_dict()
        assert d["is_held"] is True
        assert d["hold_ids"] == ["h1", "h2"]
        assert d["scope"] == "project"


class TestHoldViolationError:
    """Tests for HoldViolationError."""

    def test_basic_error(self):
        """Test creating basic error."""
        err = HoldViolationError("Resource is held")
        assert str(err) == "Resource is held"
        assert err.hold_ids == []
        assert err.resource_type is None

    def test_error_with_details(self):
        """Test error with full details."""
        err = HoldViolationError(
            "Cannot delete",
            hold_ids=["h1", "h2"],
            resource_type="run",
            resource_id="r123",
        )
        assert err.hold_ids == ["h1", "h2"]
        assert err.resource_type == "run"
        assert err.resource_id == "r123"


class TestLegalHoldMatcher:
    """Tests for LegalHoldMatcher."""

    def test_no_holds_not_held(self, matcher, store):
        """Test resource with no holds is not held."""
        result = matcher.match(
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-1",
        )
        assert result.is_held is False

    def test_direct_resource_hold(self, matcher, store):
        """Test direct resource hold is matched."""
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Discovery request",
            created_by_user_id="admin",
            resource_id="run-123",
        )
        matcher.invalidate_cache()

        result = matcher.match(
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-123",
        )

        assert result.is_held is True
        assert len(result.hold_ids) == 1
        assert result.scope == HoldScope.RESOURCE
        assert "Discovery request" in result.reasons

    def test_other_resource_not_held(self, matcher, store):
        """Test other resources are not affected by specific hold."""
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Discovery",
            created_by_user_id="admin",
            resource_id="run-123",
        )
        matcher.invalidate_cache()

        result = matcher.match(
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-456",
        )

        assert result.is_held is False

    def test_project_level_hold(self, matcher, store):
        """Test project-level hold affects all resources in project."""
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Project freeze",
            created_by_user_id="admin",
            project_id="project-1",
        )
        matcher.invalidate_cache()

        # Any run in the project should be held
        result = matcher.match(
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="any-run",
            project_id="project-1",
        )

        assert result.is_held is True
        assert result.scope == HoldScope.PROJECT

    def test_tenant_wide_hold(self, matcher, store):
        """Test tenant-wide 'all' hold affects everything."""
        store.create_legal_hold(
            tenant_id="tenant-freeze",
            resource_type="all",
            reason="Full tenant freeze",
            created_by_user_id="admin",
        )
        matcher.invalidate_cache("tenant-freeze")

        # Any resource should be held
        for rtype in ["run", "job", "report"]:
            result = matcher.match(
                tenant_id="tenant-freeze",
                resource_type=rtype,
                resource_id="any-id",
            )
            assert result.is_held is True
            assert result.scope == HoldScope.TENANT

    def test_released_hold_not_matched(self, matcher, store):
        """Test released holds are not matched."""
        hold = store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Temporary",
            created_by_user_id="admin",
            resource_id="run-1",
        )
        store.release_legal_hold(hold["id"])
        matcher.invalidate_cache()

        result = matcher.match(
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-1",
        )

        assert result.is_held is False

    def test_expired_hold_not_matched(self, matcher, store):
        """Test expired holds are not matched."""
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Expired",
            created_by_user_id="admin",
            resource_id="run-1",
            expires_at=expired,
        )
        matcher.invalidate_cache()

        result = matcher.match(
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-1",
        )

        assert result.is_held is False

    def test_multiple_holds_all_returned(self, matcher, store):
        """Test multiple matching holds are all returned."""
        # Direct hold
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Reason 1",
            created_by_user_id="admin",
            resource_id="run-1",
        )
        # Tenant-wide hold
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="all",
            reason="Reason 2",
            created_by_user_id="admin",
        )
        matcher.invalidate_cache()

        result = matcher.match(
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-1",
        )

        assert result.is_held is True
        assert len(result.hold_ids) == 2
        assert "Reason 1" in result.reasons
        assert "Reason 2" in result.reasons

    def test_is_held_shortcut(self, matcher, store):
        """Test is_held() shortcut method."""
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Test",
            created_by_user_id="admin",
            resource_id="run-1",
        )
        matcher.invalidate_cache()

        assert matcher.is_held("tenant-1", "run", "run-1") is True
        assert matcher.is_held("tenant-1", "run", "run-2") is False

    def test_cache_invalidation(self, matcher, store):
        """Test cache invalidation."""
        # Check initially not held
        assert matcher.is_held("tenant-1", "run", "run-1") is False

        # Create hold (cache still has old data)
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Test",
            created_by_user_id="admin",
            resource_id="run-1",
        )

        # Still not held due to cache
        assert matcher.is_held("tenant-1", "run", "run-1") is False

        # Invalidate cache
        matcher.invalidate_cache("tenant-1")

        # Now held
        assert matcher.is_held("tenant-1", "run", "run-1") is True


class TestCheckResourceHeld:
    """Tests for check_resource_held() function."""

    def test_not_held_returns_match(self, store):
        """Test returns match when not held."""
        result = check_resource_held(
            store,
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-1",
            raise_on_held=False,
        )
        assert result.is_held is False

    def test_held_raises_when_requested(self, store):
        """Test raises HoldViolationError when held."""
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Test hold",
            created_by_user_id="admin",
            resource_id="run-1",
        )

        with pytest.raises(HoldViolationError) as exc_info:
            check_resource_held(
                store,
                tenant_id="tenant-1",
                resource_type="run",
                resource_id="run-1",
                raise_on_held=True,
            )

        assert "Test hold" in str(exc_info.value)
        assert exc_info.value.resource_type == "run"

    def test_held_no_raise_when_disabled(self, store):
        """Test returns match without raising when disabled."""
        store.create_legal_hold(
            tenant_id="tenant-1",
            resource_type="run",
            reason="Test",
            created_by_user_id="admin",
            resource_id="run-1",
        )

        result = check_resource_held(
            store,
            tenant_id="tenant-1",
            resource_type="run",
            resource_id="run-1",
            raise_on_held=False,
        )

        assert result.is_held is True


class TestPurgeGuard:
    """Tests for purge_guard context manager."""

    def test_no_holds_all_allowed(self, store):
        """Test all resources allowed when no holds."""
        resources = [
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r1"),
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r2"),
        ]

        with purge_guard(store, resources, fail_fast=False) as result:
            assert len(result["allowed"]) == 2
            assert len(result["blocked"]) == 0

    def test_held_resource_blocked(self, store):
        """Test held resource is blocked."""
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Test",
            created_by_user_id="admin",
            resource_id="r1",
        )

        resources = [
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r1"),
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r2"),
        ]

        with purge_guard(store, resources, fail_fast=False) as result:
            assert len(result["allowed"]) == 1
            assert len(result["blocked"]) == 1
            assert result["blocked"][0].resource_id == "r1"

    def test_fail_fast_raises_immediately(self, store):
        """Test fail_fast=True raises on first held resource."""
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Test",
            created_by_user_id="admin",
            resource_id="r1",
        )

        resources = [
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r1"),
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r2"),
        ]

        with pytest.raises(HoldViolationError):
            with purge_guard(store, resources, fail_fast=True) as result:
                pass


class TestListAffectedResources:
    """Tests for list_affected_resources() function."""

    def test_tenant_wide_hold(self, store):
        """Test listing affected resources for tenant-wide hold."""
        hold = store.create_legal_hold(
            tenant_id="t1",
            resource_type="all",
            reason="Freeze",
            created_by_user_id="admin",
        )

        affected = list_affected_resources(store, hold["id"])

        assert len(affected) == 1
        assert affected[0]["scope"] == "tenant"

    def test_specific_resource_hold(self, store):
        """Test listing affected resources for specific hold."""
        hold = store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Discovery",
            created_by_user_id="admin",
            resource_id="run-123",
        )

        affected = list_affected_resources(store, hold["id"])

        assert len(affected) == 1
        assert affected[0]["scope"] == "resource"
        assert affected[0]["resource_id"] == "run-123"

    def test_project_level_hold(self, store):
        """Test listing affected resources for project hold."""
        hold = store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Project freeze",
            created_by_user_id="admin",
            project_id="proj-1",
        )

        affected = list_affected_resources(store, hold["id"])

        assert len(affected) == 1
        assert affected[0]["scope"] == "project"
        assert affected[0]["project_id"] == "proj-1"

    def test_nonexistent_hold(self, store):
        """Test listing affected resources for non-existent hold."""
        affected = list_affected_resources(store, "nonexistent")
        assert affected == []


class TestGetHoldSummary:
    """Tests for get_hold_summary() function."""

    def test_empty_summary(self, store):
        """Test summary with no holds."""
        summary = get_hold_summary(store, "tenant-1")

        assert summary["active_count"] == 0
        assert summary["total_count"] == 0
        assert summary["released_count"] == 0

    def test_summary_with_holds(self, store):
        """Test summary with various holds."""
        # Active holds
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Run hold",
            created_by_user_id="admin",
            resource_id="r1",
        )
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="all",
            reason="Tenant hold",
            created_by_user_id="admin",
        )

        # Released hold
        hold = store.create_legal_hold(
            tenant_id="t1",
            resource_type="job",
            reason="Released",
            created_by_user_id="admin",
            resource_id="j1",
        )
        store.release_legal_hold(hold["id"])

        summary = get_hold_summary(store, "t1")

        assert summary["active_count"] == 2
        assert summary["total_count"] == 3
        assert summary["released_count"] == 1
        assert summary["by_type"]["run"] == 1
        assert summary["by_type"]["all"] == 1
        assert summary["by_scope"]["resource"] == 1
        assert summary["by_scope"]["tenant"] == 1
