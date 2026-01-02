"""
Unit tests for legal hold release and expiry logic (v4.3.0 PR1).

Tests:
- Legal hold creation
- Manual release (released_at)
- Automatic expiry (expires_at)
- is_resource_held() checks
- Active hold filtering
"""

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_store import ComplianceStore, ResourceType


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def store(temp_db):
    """Create a ComplianceStore with temporary database."""
    return ComplianceStore(db_path=temp_db)


class TestLegalHoldCreation:
    """Tests for legal hold creation."""

    def test_create_basic_legal_hold(self, store):
        """Test creating a basic legal hold."""
        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Legal investigation",
            created_by_user_id="user-admin",
        )

        assert hold["id"] is not None
        assert hold["tenant_id"] == "tenant-001"
        assert hold["resource_type"] == "run"
        assert hold["reason"] == "Legal investigation"
        assert hold["created_by_user_id"] == "user-admin"
        assert hold["released_at"] is None
        assert hold["expires_at"] is None

    def test_create_hold_with_expiry(self, store):
        """Test creating a legal hold with expiry date."""
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="project",
            reason="Audit requirement",
            created_by_user_id="user-admin",
            project_id="project-001",
            expires_at=expires,
        )

        assert hold["expires_at"] == expires

    def test_create_hold_for_specific_resource(self, store):
        """Test creating a hold for a specific resource ID."""
        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Discovery request",
            created_by_user_id="user-legal",
            resource_id="run-12345",
        )

        assert hold["resource_id"] == "run-12345"

    def test_create_tenant_wide_hold(self, store):
        """Test creating a tenant-wide 'all' hold."""
        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="all",
            reason="Full tenant freeze",
            created_by_user_id="user-admin",
        )

        assert hold["resource_type"] == "all"
        assert hold["project_id"] is None
        assert hold["resource_id"] is None


class TestLegalHoldRelease:
    """Tests for manual legal hold release."""

    def test_release_active_hold(self, store):
        """Test releasing an active legal hold."""
        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Investigation",
            created_by_user_id="user-admin",
        )

        assert hold["released_at"] is None

        # Release the hold
        released = store.release_legal_hold(hold["id"])

        assert released["released_at"] is not None
        assert released["id"] == hold["id"]

    def test_release_already_released_hold(self, store):
        """Test that releasing an already released hold keeps original release time."""
        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Investigation",
            created_by_user_id="user-admin",
        )

        # First release
        released1 = store.release_legal_hold(hold["id"])
        first_release_time = released1["released_at"]

        # Second release attempt (should not change)
        released2 = store.release_legal_hold(hold["id"])
        assert released2["released_at"] == first_release_time

    def test_release_nonexistent_hold(self, store):
        """Test releasing a non-existent hold returns None."""
        result = store.release_legal_hold("nonexistent-id")
        assert result is None


class TestLegalHoldExpiry:
    """Tests for automatic legal hold expiry."""

    def test_expired_hold_not_active(self, store):
        """Test that expired holds are not considered active."""
        # Create hold that expired yesterday
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Short hold",
            created_by_user_id="user-admin",
            resource_id="run-001",
            expires_at=expired,
        )

        # Should not be held (expired)
        is_held = store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            resource_id="run-001",
        )

        assert is_held is False

    def test_future_expiry_still_active(self, store):
        """Test that future expiry holds are still active."""
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Future hold",
            created_by_user_id="user-admin",
            resource_id="run-002",
            expires_at=future,
        )

        is_held = store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            resource_id="run-002",
        )

        assert is_held is True

    def test_no_expiry_always_active(self, store):
        """Test that holds without expiry are always active (until released)."""
        store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Indefinite hold",
            created_by_user_id="user-admin",
            resource_id="run-003",
            expires_at=None,
        )

        is_held = store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            resource_id="run-003",
        )

        assert is_held is True


class TestIsResourceHeld:
    """Tests for is_resource_held() check logic."""

    def test_direct_resource_hold(self, store):
        """Test direct hold on a specific resource."""
        store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Direct hold",
            created_by_user_id="user-admin",
            resource_id="run-specific",
        )

        # Should be held
        assert store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            resource_id="run-specific",
        ) is True

        # Different resource should not be held
        assert store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            resource_id="run-other",
        ) is False

    def test_project_level_hold(self, store):
        """Test project-level hold affects all resources in project."""
        store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Project-wide run hold",
            created_by_user_id="user-admin",
            project_id="project-001",
        )

        # Any run in the project should be held
        assert store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            project_id="project-001",
        ) is True

        # Run in different project not held
        assert store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            project_id="project-002",
        ) is False

    def test_tenant_wide_all_hold(self, store):
        """Test tenant-wide 'all' hold affects everything."""
        store.create_legal_hold(
            tenant_id="tenant-freeze",
            resource_type="all",
            reason="Tenant freeze",
            created_by_user_id="user-admin",
        )

        # Everything in tenant should be held
        assert store.is_resource_held(
            tenant_id="tenant-freeze",
            resource_type="run",
            resource_id="any-run",
        ) is True

        assert store.is_resource_held(
            tenant_id="tenant-freeze",
            resource_type="job",
            resource_id="any-job",
        ) is True

        # Different tenant not affected
        assert store.is_resource_held(
            tenant_id="tenant-other",
            resource_type="run",
            resource_id="any-run",
        ) is False

    def test_released_hold_not_active(self, store):
        """Test that released holds don't block resources."""
        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Temporary hold",
            created_by_user_id="user-admin",
            resource_id="run-released",
        )

        # Initially held
        assert store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            resource_id="run-released",
        ) is True

        # Release
        store.release_legal_hold(hold["id"])

        # No longer held
        assert store.is_resource_held(
            tenant_id="tenant-001",
            resource_type="run",
            resource_id="run-released",
        ) is False


class TestListLegalHolds:
    """Tests for listing legal holds."""

    def test_list_all_holds_for_tenant(self, store):
        """Test listing all holds for a tenant."""
        # Create multiple holds
        store.create_legal_hold(
            tenant_id="tenant-list",
            resource_type="run",
            reason="Hold 1",
            created_by_user_id="user-admin",
        )
        store.create_legal_hold(
            tenant_id="tenant-list",
            resource_type="job",
            reason="Hold 2",
            created_by_user_id="user-admin",
        )

        holds = store.list_legal_holds(tenant_id="tenant-list", active_only=False)
        assert len(holds) == 2

    def test_list_active_holds_only(self, store):
        """Test listing only active (non-released, non-expired) holds."""
        # Create active hold
        store.create_legal_hold(
            tenant_id="tenant-active",
            resource_type="run",
            reason="Active hold",
            created_by_user_id="user-admin",
        )

        # Create and release a hold
        released_hold = store.create_legal_hold(
            tenant_id="tenant-active",
            resource_type="job",
            reason="Released hold",
            created_by_user_id="user-admin",
        )
        store.release_legal_hold(released_hold["id"])

        # Create expired hold
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        store.create_legal_hold(
            tenant_id="tenant-active",
            resource_type="project",
            reason="Expired hold",
            created_by_user_id="user-admin",
            expires_at=expired,
        )

        # Only active holds
        active_holds = store.list_legal_holds(tenant_id="tenant-active", active_only=True)
        assert len(active_holds) == 1
        assert active_holds[0]["reason"] == "Active hold"

        # All holds
        all_holds = store.list_legal_holds(tenant_id="tenant-active", active_only=False)
        assert len(all_holds) == 3

    def test_list_holds_for_project(self, store):
        """Test filtering holds by project."""
        # Tenant-level hold
        store.create_legal_hold(
            tenant_id="tenant-proj",
            resource_type="all",
            reason="Tenant hold",
            created_by_user_id="user-admin",
        )

        # Project-specific hold
        store.create_legal_hold(
            tenant_id="tenant-proj",
            resource_type="run",
            reason="Project hold",
            created_by_user_id="user-admin",
            project_id="project-x",
        )

        # List for project should include tenant-level and project-specific
        project_holds = store.list_legal_holds(
            tenant_id="tenant-proj",
            project_id="project-x",
        )
        assert len(project_holds) == 2

    def test_get_single_hold(self, store):
        """Test getting a single hold by ID."""
        hold = store.create_legal_hold(
            tenant_id="tenant-001",
            resource_type="run",
            reason="Get test",
            created_by_user_id="user-admin",
        )

        retrieved = store.get_legal_hold(hold["id"])
        assert retrieved["id"] == hold["id"]
        assert retrieved["reason"] == "Get test"

    def test_get_nonexistent_hold(self, store):
        """Test getting non-existent hold returns None."""
        result = store.get_legal_hold("nonexistent-hold-id")
        assert result is None
