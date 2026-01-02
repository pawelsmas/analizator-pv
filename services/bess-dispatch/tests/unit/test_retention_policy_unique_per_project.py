"""
Unit tests for retention policy uniqueness constraints (v4.3.0 PR1).

Tests:
- UNIQUE(tenant_id, project_id) constraint
- Tenant-level policy (project_id IS NULL) uniqueness
- Project-level policy uniqueness
- Multiple tenants can have same project_id
"""

import os
import sys
import sqlite3
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_store import ComplianceStore


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


class TestRetentionPolicyUniqueness:
    """Tests for retention policy UNIQUE(tenant_id, project_id) constraint."""

    def test_tenant_level_policy_uniqueness(self, store):
        """Test that tenant can only have one tenant-level policy (project_id IS NULL)."""
        tenant_id = "tenant-001"
        policy_json = {"runs_days": 365, "jobs_days": 90}

        # First creation should succeed
        policy1 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json=policy_json,
            project_id=None,
        )
        assert policy1["id"] is not None
        assert policy1["tenant_id"] == tenant_id
        assert policy1["project_id"] is None

        # Second creation with same tenant (no project) should fail
        with pytest.raises(sqlite3.IntegrityError):
            store.create_retention_policy(
                tenant_id=tenant_id,
                policy_json={"runs_days": 180},
                project_id=None,
            )

    def test_project_level_policy_uniqueness(self, store):
        """Test that tenant+project combination is unique."""
        tenant_id = "tenant-002"
        project_id = "project-001"
        policy_json = {"runs_days": 180}

        # First creation should succeed
        policy1 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json=policy_json,
            project_id=project_id,
        )
        assert policy1["project_id"] == project_id

        # Second creation with same tenant+project should fail
        with pytest.raises(sqlite3.IntegrityError):
            store.create_retention_policy(
                tenant_id=tenant_id,
                policy_json={"runs_days": 90},
                project_id=project_id,
            )

    def test_different_projects_same_tenant(self, store):
        """Test that same tenant can have policies for different projects."""
        tenant_id = "tenant-003"

        # Tenant-level policy
        policy1 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 365},
            project_id=None,
        )

        # Project A policy
        policy2 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 180},
            project_id="project-a",
        )

        # Project B policy
        policy3 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 90},
            project_id="project-b",
        )

        # All should have different IDs
        assert policy1["id"] != policy2["id"] != policy3["id"]

        # Verify retrieval
        retrieved1 = store.get_retention_policy(tenant_id, project_id=None)
        assert retrieved1["policy_json"]["runs_days"] == 365

        retrieved2 = store.get_retention_policy(tenant_id, project_id="project-a")
        assert retrieved2["policy_json"]["runs_days"] == 180

        retrieved3 = store.get_retention_policy(tenant_id, project_id="project-b")
        assert retrieved3["policy_json"]["runs_days"] == 90

    def test_same_project_different_tenants(self, store):
        """Test that different tenants can have policies for same project_id."""
        project_id = "shared-project"

        # Tenant A policy for project
        policy1 = store.create_retention_policy(
            tenant_id="tenant-a",
            policy_json={"runs_days": 365},
            project_id=project_id,
        )

        # Tenant B policy for same project_id (different tenant)
        policy2 = store.create_retention_policy(
            tenant_id="tenant-b",
            policy_json={"runs_days": 180},
            project_id=project_id,
        )

        # Both should succeed
        assert policy1["id"] != policy2["id"]
        assert policy1["tenant_id"] == "tenant-a"
        assert policy2["tenant_id"] == "tenant-b"

    def test_update_existing_policy(self, store):
        """Test updating existing policy instead of creating duplicate."""
        tenant_id = "tenant-004"
        project_id = "project-001"

        # Create policy
        policy1 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 365},
            project_id=project_id,
        )

        # Update should work
        updated = store.update_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 180},
            project_id=project_id,
        )

        assert updated["id"] == policy1["id"]
        assert updated["policy_json"]["runs_days"] == 180

    def test_delete_and_recreate(self, store):
        """Test that after deletion, same tenant+project can be recreated."""
        tenant_id = "tenant-005"
        project_id = "project-001"

        # Create
        policy1 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 365},
            project_id=project_id,
        )

        # Delete
        deleted = store.delete_retention_policy(tenant_id, project_id)
        assert deleted is True

        # Recreate should work
        policy2 = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 180},
            project_id=project_id,
        )

        assert policy2["id"] != policy1["id"]
        assert policy2["policy_json"]["runs_days"] == 180

    def test_policy_enabled_flag(self, store):
        """Test enabled/disabled state for policies."""
        tenant_id = "tenant-006"

        # Create enabled policy
        policy = store.create_retention_policy(
            tenant_id=tenant_id,
            policy_json={"runs_days": 365},
            enabled=True,
        )
        assert policy["enabled"] is True

        # Update to disabled
        updated = store.update_retention_policy(
            tenant_id=tenant_id,
            enabled=False,
        )
        assert updated["enabled"] is False

        # Create disabled policy from start
        policy2 = store.create_retention_policy(
            tenant_id="tenant-007",
            policy_json={"runs_days": 90},
            enabled=False,
        )
        assert policy2["enabled"] is False

    def test_get_nonexistent_policy(self, store):
        """Test getting policy that doesn't exist returns None."""
        result = store.get_retention_policy("nonexistent-tenant")
        assert result is None

        result = store.get_retention_policy("nonexistent-tenant", project_id="any")
        assert result is None

    def test_delete_nonexistent_policy(self, store):
        """Test deleting policy that doesn't exist returns False."""
        deleted = store.delete_retention_policy("nonexistent-tenant")
        assert deleted is False
