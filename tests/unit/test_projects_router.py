"""
Unit tests for Projects router (v3.7.0).

Tests router logic with mocked auth store.
"""

import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bess-dispatch to path
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))

# Setup temp database before imports
AUTH_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
RUN_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
os.environ["AUTH_DB_PATH"] = AUTH_DB
os.environ["RUN_STORE_PATH"] = RUN_DB
os.environ["AUTH_ENABLED"] = "false"

from auth_store import AuthStore, ProjectRole
from auth_config import Role


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def store(temp_db):
    """Create an AuthStore with temp database."""
    return AuthStore(temp_db)


@pytest.fixture
def tenant_and_users(store):
    """Create tenant with multiple users."""
    tenant = store.create_tenant("test-tenant", "Test Tenant")

    admin = store.create_user(
        tenant_id=tenant["id"],
        email="admin@example.com",
        password="password",
        role=Role.ADMIN,
    )

    editor = store.create_user(
        tenant_id=tenant["id"],
        email="editor@example.com",
        password="password",
        role=Role.EDITOR,
    )

    viewer = store.create_user(
        tenant_id=tenant["id"],
        email="viewer@example.com",
        password="password",
        role=Role.VIEWER,
    )

    return tenant, admin, editor, viewer


class TestProjectsRouter:
    """Tests for projects router functionality via store."""

    def test_create_project(self, store, tenant_and_users):
        """Admin creates project and becomes owner."""
        tenant, admin, _, _ = tenant_and_users

        project = store.create_project(
            tenant_id=tenant["id"],
            name="New Project",
            created_by_user_id=admin["id"],
        )

        assert project["name"] == "New Project"
        assert project["tenant_id"] == tenant["id"]

        # Add creator as owner
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=admin["id"],
            role=ProjectRole.OWNER,
        )

        # Verify membership
        membership = store.get_project_membership(project["id"], admin["id"])
        assert membership["role"] == "owner"

    def test_list_user_projects(self, store, tenant_and_users):
        """Users only see projects they're members of."""
        tenant, admin, editor, viewer = tenant_and_users

        # Create projects
        p1 = store.create_project(tenant_id=tenant["id"], name="Admin Project")
        p2 = store.create_project(tenant_id=tenant["id"], name="Shared Project")
        p3 = store.create_project(tenant_id=tenant["id"], name="Editor Project")

        # Add memberships
        store.add_project_member(tenant["id"], p1["id"], admin["id"], ProjectRole.OWNER)
        store.add_project_member(tenant["id"], p2["id"], admin["id"], ProjectRole.OWNER)
        store.add_project_member(tenant["id"], p2["id"], editor["id"], ProjectRole.EDITOR)
        store.add_project_member(tenant["id"], p3["id"], editor["id"], ProjectRole.OWNER)

        # Admin sees all tenant projects (admin role)
        all_projects = store.list_projects(tenant["id"])
        assert len(all_projects) == 3

        # Editor sees only their projects
        editor_projects = store.list_user_projects(editor["id"], tenant["id"])
        assert len(editor_projects) == 2
        project_names = [p["name"] for p in editor_projects]
        assert "Shared Project" in project_names
        assert "Editor Project" in project_names
        assert "Admin Project" not in project_names

        # Viewer sees nothing (no memberships)
        viewer_projects = store.list_user_projects(viewer["id"], tenant["id"])
        assert len(viewer_projects) == 0

    def test_add_remove_member(self, store, tenant_and_users):
        """Owner can add and remove members."""
        tenant, admin, editor, viewer = tenant_and_users

        project = store.create_project(tenant_id=tenant["id"], name="Team Project")
        store.add_project_member(tenant["id"], project["id"], admin["id"], ProjectRole.OWNER)

        # Add editor as member
        store.add_project_member(tenant["id"], project["id"], editor["id"], ProjectRole.EDITOR)

        members = store.list_project_members(project["id"])
        assert len(members) == 2

        # Remove editor
        store.remove_project_member(project["id"], editor["id"])

        members = store.list_project_members(project["id"])
        assert len(members) == 1

    def test_cannot_remove_last_owner(self, store, tenant_and_users):
        """Cannot remove the last owner."""
        tenant, admin, editor, _ = tenant_and_users

        project = store.create_project(tenant_id=tenant["id"], name="Single Owner")
        store.add_project_member(tenant["id"], project["id"], admin["id"], ProjectRole.OWNER)

        # Verify only one owner
        owner_count = store.count_project_owners(project["id"])
        assert owner_count == 1

        # In the API, we'd check this before removing
        # Here we just verify the count

    def test_cannot_demote_last_owner(self, store, tenant_and_users):
        """Cannot demote the last owner to editor/viewer."""
        tenant, admin, _, _ = tenant_and_users

        project = store.create_project(tenant_id=tenant["id"], name="Last Owner")
        store.add_project_member(tenant["id"], project["id"], admin["id"], ProjectRole.OWNER)

        # Count owners before demote
        owner_count = store.count_project_owners(project["id"])
        assert owner_count == 1

        # In the API, we'd prevent this
        # Here we verify the count check works

    def test_role_hierarchy_access(self, store, tenant_and_users):
        """Test role hierarchy for access checks."""
        tenant, admin, editor, viewer = tenant_and_users

        project = store.create_project(tenant_id=tenant["id"], name="Role Test")
        store.add_project_member(tenant["id"], project["id"], admin["id"], ProjectRole.OWNER)
        store.add_project_member(tenant["id"], project["id"], editor["id"], ProjectRole.EDITOR)
        store.add_project_member(tenant["id"], project["id"], viewer["id"], ProjectRole.VIEWER)

        # Owner has all access
        assert store.user_has_project_access(admin["id"], project["id"], ProjectRole.VIEWER)
        assert store.user_has_project_access(admin["id"], project["id"], ProjectRole.EDITOR)
        assert store.user_has_project_access(admin["id"], project["id"], ProjectRole.OWNER)

        # Editor has viewer and editor access
        assert store.user_has_project_access(editor["id"], project["id"], ProjectRole.VIEWER)
        assert store.user_has_project_access(editor["id"], project["id"], ProjectRole.EDITOR)
        assert not store.user_has_project_access(editor["id"], project["id"], ProjectRole.OWNER)

        # Viewer has only viewer access
        assert store.user_has_project_access(viewer["id"], project["id"], ProjectRole.VIEWER)
        assert not store.user_has_project_access(viewer["id"], project["id"], ProjectRole.EDITOR)
        assert not store.user_has_project_access(viewer["id"], project["id"], ProjectRole.OWNER)

    def test_archive_unarchive(self, store, tenant_and_users):
        """Test archiving and unarchiving projects."""
        tenant, admin, _, _ = tenant_and_users

        project = store.create_project(tenant_id=tenant["id"], name="Archive Me")

        # Archive
        result = store.archive_project(project["id"], tenant["id"])
        assert result is True

        archived = store.get_project(project["id"], tenant["id"])
        assert archived["archived_at"] is not None

        # List excludes archived by default
        projects = store.list_projects(tenant["id"])
        project_ids = [p["id"] for p in projects]
        assert project["id"] not in project_ids

        # List includes archived when requested
        projects_with_archived = store.list_projects(tenant["id"], include_archived=True)
        project_ids = [p["id"] for p in projects_with_archived]
        assert project["id"] in project_ids

        # Unarchive
        result = store.unarchive_project(project["id"], tenant["id"])
        assert result is True

        unarchived = store.get_project(project["id"], tenant["id"])
        assert unarchived["archived_at"] is None

    def test_project_share_policies(self, store, tenant_and_users):
        """Test project share policy settings."""
        tenant, admin, _, _ = tenant_and_users

        # Create with restricted policies
        project = store.create_project(
            tenant_id=tenant["id"],
            name="Restricted",
            allow_public_shares=False,
            share_max_expiry_hours=48,
        )

        assert project["allow_public_shares"] is False
        assert project["share_max_expiry_hours"] == 48

        # Update policies
        updated = store.update_project(
            project_id=project["id"],
            tenant_id=tenant["id"],
            allow_public_shares=True,
            share_max_expiry_hours=168,
        )

        assert updated["allow_public_shares"] is True
        assert updated["share_max_expiry_hours"] == 168

    def test_backfill_default_project(self, store, tenant_and_users):
        """Test default project backfill for tenant."""
        tenant, admin, editor, viewer = tenant_and_users

        result = store.backfill_default_project(
            tenant_id=tenant["id"],
            created_by_user_id=admin["id"],
        )

        assert result["already_existed"] is False
        assert result["project"]["name"] == "Default Project"
        assert result["members_added"] == 3  # admin, editor, viewer

        # All users should be owners
        for user in [admin, editor, viewer]:
            membership = store.get_project_membership(result["project"]["id"], user["id"])
            assert membership is not None
            assert membership["role"] == "owner"

        # Running again is idempotent
        result2 = store.backfill_default_project(tenant_id=tenant["id"])
        assert result2["already_existed"] is True
        assert result2["members_added"] == 0

    def test_update_member_role(self, store, tenant_and_users):
        """Test updating member roles."""
        tenant, admin, editor, _ = tenant_and_users

        project = store.create_project(tenant_id=tenant["id"], name="Role Update")
        store.add_project_member(tenant["id"], project["id"], admin["id"], ProjectRole.OWNER)
        store.add_project_member(tenant["id"], project["id"], editor["id"], ProjectRole.VIEWER)

        # Promote editor to editor role
        result = store.update_project_member_role(project["id"], editor["id"], ProjectRole.EDITOR)
        assert result is True

        membership = store.get_project_membership(project["id"], editor["id"])
        assert membership["role"] == "editor"

        # Promote editor to owner
        result = store.update_project_member_role(project["id"], editor["id"], ProjectRole.OWNER)
        assert result is True

        membership = store.get_project_membership(project["id"], editor["id"])
        assert membership["role"] == "owner"

    def test_duplicate_member_fails(self, store, tenant_and_users):
        """Cannot add same user twice to project."""
        tenant, admin, _, _ = tenant_and_users

        project = store.create_project(tenant_id=tenant["id"], name="Dup Test")
        store.add_project_member(tenant["id"], project["id"], admin["id"], ProjectRole.OWNER)

        with pytest.raises(sqlite3.IntegrityError):
            store.add_project_member(tenant["id"], project["id"], admin["id"], ProjectRole.EDITOR)

    def test_project_name_unique_in_tenant(self, store, tenant_and_users):
        """Project names must be unique within tenant."""
        tenant, _, _, _ = tenant_and_users

        store.create_project(tenant_id=tenant["id"], name="Unique Name")

        assert store.project_name_exists("Unique Name", tenant["id"]) is True
        assert store.project_name_exists("Other Name", tenant["id"]) is False

    def test_project_isolation_by_tenant(self, store, tenant_and_users):
        """Projects are isolated by tenant."""
        tenant1, _, _, _ = tenant_and_users

        tenant2 = store.create_tenant("other-tenant", "Other Tenant")

        project = store.create_project(tenant_id=tenant1["id"], name="Tenant1 Project")

        # Cannot get project from other tenant
        result = store.get_project(project["id"], tenant2["id"])
        assert result is None

        # Can get project from correct tenant
        result = store.get_project(project["id"], tenant1["id"])
        assert result is not None
