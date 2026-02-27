"""
Unit tests for Share token rotation and revoke-all (v3.8.0 PR2).

Tests for auth_store share rotation and bulk revocation:
- rotate_share_token
- revoke_all_shares_for_project
- revoke_all_shares_for_resource
- count_active_shares_for_project
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add bess-dispatch to path
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def auth_store(temp_db):
    """Create AuthStore with temporary database."""
    from auth_store import AuthStore
    store = AuthStore(db_path=temp_db)
    store.create_tenant("test_tenant", "Test Tenant")
    from auth_config import Role
    store.create_user("test_tenant", "test@test.com", "password123", Role.ADMIN)
    return store


@pytest.fixture
def test_project(auth_store):
    """Create a test project."""
    return auth_store.create_project(
        tenant_id="test_tenant",
        name="Test Project",
        created_by_user_id="user_123",
    )


class TestRotateShareToken:
    """Tests for rotate_share_token."""

    def test_rotate_returns_new_token(self, auth_store):
        """rotate_share_token returns new token and increments version."""
        # Create a share
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )
        original_token = share["token"]
        assert share["token_version"] == 1

        # Rotate token
        result = auth_store.rotate_share_token(share["id"], "test_tenant")

        assert result is not None
        assert result["token"] != original_token
        assert result["token_version"] == 2

    def test_rotate_invalidates_old_token(self, auth_store):
        """After rotation, old token no longer works."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )
        original_token = share["token"]

        # Rotate token
        auth_store.rotate_share_token(share["id"], "test_tenant")

        # Old token should not find the share
        old_share = auth_store.get_share_by_token(original_token)
        assert old_share is None

    def test_rotate_new_token_works(self, auth_store):
        """After rotation, new token works."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )

        # Rotate token
        result = auth_store.rotate_share_token(share["id"], "test_tenant")
        new_token = result["token"]

        # New token should find the share
        found_share = auth_store.get_share_by_token(new_token)
        assert found_share is not None
        assert found_share["id"] == share["id"]

    def test_rotate_not_found(self, auth_store):
        """rotate_share_token returns None for non-existent share."""
        result = auth_store.rotate_share_token("nonexistent_id", "test_tenant")
        assert result is None

    def test_rotate_revoked_share(self, auth_store):
        """rotate_share_token returns None for revoked share."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )

        # Revoke the share
        auth_store.revoke_share(share["id"], "test_tenant")

        # Try to rotate
        result = auth_store.rotate_share_token(share["id"], "test_tenant")
        assert result is None

    def test_rotate_multiple_times(self, auth_store):
        """Token can be rotated multiple times."""
        share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_123",
            created_by="user_123",
        )

        # Rotate 3 times
        for i in range(3):
            result = auth_store.rotate_share_token(share["id"], "test_tenant")
            assert result["token_version"] == i + 2

        # Final version should be 4
        updated = auth_store.get_share_by_id(share["id"], "test_tenant")
        assert updated["token_version"] == 4


class TestRevokeAllSharesForProject:
    """Tests for revoke_all_shares_for_project."""

    def test_revokes_all_project_shares(self, auth_store, test_project):
        """revoke_all_shares_for_project revokes all shares for the project."""
        project_id = test_project["id"]

        # Create multiple shares for the project
        for i in range(3):
            auth_store.create_share(
                tenant_id="test_tenant",
                resource_type="run",
                resource_id=f"run_{i}",
                created_by="user_123",
                project_id=project_id,
            )

        # Revoke all
        count = auth_store.revoke_all_shares_for_project(project_id, "test_tenant")
        assert count == 3

        # Verify all are revoked
        shares = auth_store.list_shares("test_tenant", project_id=project_id)
        for share in shares:
            assert share["revoked_at"] is not None

    def test_does_not_revoke_other_projects(self, auth_store, test_project):
        """revoke_all_shares_for_project only revokes shares for specified project."""
        project1_id = test_project["id"]

        # Create another project
        project2 = auth_store.create_project(
            tenant_id="test_tenant",
            name="Other Project",
            created_by_user_id="user_123",
        )
        project2_id = project2["id"]

        # Create shares for both projects
        auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_1",
            created_by="user_123",
            project_id=project1_id,
        )
        share2 = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_2",
            created_by="user_123",
            project_id=project2_id,
        )

        # Revoke all for project1
        auth_store.revoke_all_shares_for_project(project1_id, "test_tenant")

        # Project2 share should still be active
        project2_share = auth_store.get_share_by_id(share2["id"], "test_tenant")
        assert project2_share["revoked_at"] is None

    def test_returns_zero_for_no_shares(self, auth_store, test_project):
        """revoke_all_shares_for_project returns 0 when no shares exist."""
        count = auth_store.revoke_all_shares_for_project(test_project["id"], "test_tenant")
        assert count == 0

    def test_skips_already_revoked(self, auth_store, test_project):
        """revoke_all_shares_for_project skips already revoked shares."""
        project_id = test_project["id"]

        # Create shares
        share1 = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_1",
            created_by="user_123",
            project_id=project_id,
        )
        auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_2",
            created_by="user_123",
            project_id=project_id,
        )

        # Revoke first one manually
        auth_store.revoke_share(share1["id"], "test_tenant")

        # Revoke all - should only count the second one
        count = auth_store.revoke_all_shares_for_project(project_id, "test_tenant")
        assert count == 1


class TestRevokeAllSharesForResource:
    """Tests for revoke_all_shares_for_resource."""

    def test_revokes_all_resource_shares(self, auth_store):
        """revoke_all_shares_for_resource revokes all shares for the resource."""
        resource_id = "run_123"

        # Create multiple shares for the same resource
        for i in range(3):
            auth_store.create_share(
                tenant_id="test_tenant",
                resource_type="run",
                resource_id=resource_id,
                created_by="user_123",
                label=f"Share {i}",
            )

        # Revoke all
        count = auth_store.revoke_all_shares_for_resource("run", resource_id, "test_tenant")
        assert count == 3

    def test_does_not_revoke_other_resources(self, auth_store):
        """revoke_all_shares_for_resource only revokes shares for specified resource."""
        # Create shares for different resources
        share1 = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_1",
            created_by="user_123",
        )
        share2 = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_2",
            created_by="user_123",
        )

        # Revoke all for run_1
        auth_store.revoke_all_shares_for_resource("run", "run_1", "test_tenant")

        # run_2 share should still be active
        other_share = auth_store.get_share_by_id(share2["id"], "test_tenant")
        assert other_share["revoked_at"] is None


class TestCountActiveSharesForProject:
    """Tests for count_active_shares_for_project."""

    def test_counts_active_shares(self, auth_store, test_project):
        """count_active_shares_for_project counts non-revoked, non-expired shares."""
        project_id = test_project["id"]

        # Create 3 active shares
        for i in range(3):
            auth_store.create_share(
                tenant_id="test_tenant",
                resource_type="run",
                resource_id=f"run_{i}",
                created_by="user_123",
                project_id=project_id,
            )

        count = auth_store.count_active_shares_for_project(project_id, "test_tenant")
        assert count == 3

    def test_excludes_revoked_shares(self, auth_store, test_project):
        """count_active_shares_for_project excludes revoked shares."""
        project_id = test_project["id"]

        share1 = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_1",
            created_by="user_123",
            project_id=project_id,
        )
        auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_2",
            created_by="user_123",
            project_id=project_id,
        )

        # Revoke first one
        auth_store.revoke_share(share1["id"], "test_tenant")

        count = auth_store.count_active_shares_for_project(project_id, "test_tenant")
        assert count == 1

    def test_returns_zero_for_no_shares(self, auth_store, test_project):
        """count_active_shares_for_project returns 0 when no shares exist."""
        count = auth_store.count_active_shares_for_project(test_project["id"], "test_tenant")
        assert count == 0


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
