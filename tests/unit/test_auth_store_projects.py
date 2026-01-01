"""
Unit tests for auth_store projects and memberships (v3.7.0).

Tests:
- Project CRUD operations
- Membership CRUD operations
- Project role hierarchy
- Default project backfill
- Unique constraints
- Share policies
"""

import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# Add bess-dispatch to path
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))

from auth_store import (
    AuthStore,
    ProjectRole,
    DEFAULT_PROJECT_NAME,
)
from auth_config import Role


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def store(temp_db):
    """Create an AuthStore instance with temp database."""
    # Disable auth for testing
    os.environ["AUTH_ENABLED"] = "false"
    return AuthStore(temp_db)


@pytest.fixture
def tenant_and_user(store):
    """Create a tenant and user for testing."""
    tenant = store.create_tenant("test-tenant", "Test Tenant")
    user = store.create_user(
        tenant_id=tenant["id"],
        email="test@example.com",
        password="password123",
        role=Role.ADMIN,
    )
    return tenant, user


class TestProjectRole:
    """Tests for ProjectRole enum."""

    def test_owner_value(self):
        assert ProjectRole.OWNER.value == "owner"

    def test_editor_value(self):
        assert ProjectRole.EDITOR.value == "editor"

    def test_viewer_value(self):
        assert ProjectRole.VIEWER.value == "viewer"


class TestProjectCRUD:
    """Tests for project CRUD operations."""

    def test_create_project(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="My Project",
            created_by_user_id=user["id"],
        )

        assert project["id"] is not None
        assert project["tenant_id"] == tenant["id"]
        assert project["name"] == "My Project"
        assert project["created_at"] is not None
        assert project["archived_at"] is None
        assert project["created_by_user_id"] == user["id"]
        assert project["allow_public_shares"] is True
        assert project["share_max_expiry_hours"] is None

    def test_create_project_with_share_policy(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Restricted Project",
            allow_public_shares=False,
            share_max_expiry_hours=72,
        )

        assert project["allow_public_shares"] is False
        assert project["share_max_expiry_hours"] == 72

    def test_create_project_with_custom_id(self, store, tenant_and_user):
        tenant, _ = tenant_and_user
        custom_id = str(uuid.uuid4())

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Custom ID Project",
            project_id=custom_id,
        )

        assert project["id"] == custom_id

    def test_get_project(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        created = store.create_project(
            tenant_id=tenant["id"],
            name="Get Test",
            created_by_user_id=user["id"],
        )

        fetched = store.get_project(created["id"], tenant["id"])

        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "Get Test"

    def test_get_project_wrong_tenant(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Isolated Project",
        )

        # Try to get with different tenant
        fetched = store.get_project(project["id"], "other-tenant")
        assert fetched is None

    def test_get_project_not_found(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        fetched = store.get_project("nonexistent-id", tenant["id"])
        assert fetched is None

    def test_list_projects(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        store.create_project(tenant_id=tenant["id"], name="Project A")
        store.create_project(tenant_id=tenant["id"], name="Project B")
        store.create_project(tenant_id=tenant["id"], name="Project C")

        projects = store.list_projects(tenant["id"])

        assert len(projects) == 3
        names = [p["name"] for p in projects]
        assert "Project A" in names
        assert "Project B" in names
        assert "Project C" in names

    def test_list_projects_excludes_archived(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        p1 = store.create_project(tenant_id=tenant["id"], name="Active")
        p2 = store.create_project(tenant_id=tenant["id"], name="Archived")

        store.archive_project(p2["id"], tenant["id"])

        projects = store.list_projects(tenant["id"])
        assert len(projects) == 1
        assert projects[0]["name"] == "Active"

    def test_list_projects_include_archived(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        store.create_project(tenant_id=tenant["id"], name="Active")
        p2 = store.create_project(tenant_id=tenant["id"], name="Archived")

        store.archive_project(p2["id"], tenant["id"])

        projects = store.list_projects(tenant["id"], include_archived=True)
        assert len(projects) == 2

    def test_update_project_name(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Original Name",
        )

        updated = store.update_project(
            project_id=project["id"],
            tenant_id=tenant["id"],
            name="New Name",
        )

        assert updated is not None
        assert updated["name"] == "New Name"

    def test_update_project_share_policy(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Policy Test",
            allow_public_shares=True,
        )

        updated = store.update_project(
            project_id=project["id"],
            tenant_id=tenant["id"],
            allow_public_shares=False,
            share_max_expiry_hours=48,
        )

        assert updated["allow_public_shares"] is False
        assert updated["share_max_expiry_hours"] == 48

    def test_update_project_not_found(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        result = store.update_project(
            project_id="nonexistent",
            tenant_id=tenant["id"],
            name="New Name",
        )

        assert result is None

    def test_archive_project(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="To Archive",
        )

        result = store.archive_project(project["id"], tenant["id"])
        assert result is True

        archived = store.get_project(project["id"], tenant["id"])
        assert archived["archived_at"] is not None

    def test_archive_project_idempotent(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Archive Test",
        )

        store.archive_project(project["id"], tenant["id"])
        result = store.archive_project(project["id"], tenant["id"])

        # Second archive returns False (already archived)
        assert result is False

    def test_unarchive_project(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Unarchive Test",
        )

        store.archive_project(project["id"], tenant["id"])
        result = store.unarchive_project(project["id"], tenant["id"])

        assert result is True

        unarchived = store.get_project(project["id"], tenant["id"])
        assert unarchived["archived_at"] is None

    def test_project_name_exists(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        store.create_project(tenant_id=tenant["id"], name="Unique Name")

        assert store.project_name_exists("Unique Name", tenant["id"]) is True
        assert store.project_name_exists("Other Name", tenant["id"]) is False

    def test_project_name_exists_exclude(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        project = store.create_project(tenant_id=tenant["id"], name="My Name")

        # Same name, same project = OK (for updates)
        assert store.project_name_exists(
            "My Name", tenant["id"], exclude_project_id=project["id"]
        ) is False


class TestProjectMembership:
    """Tests for project membership operations."""

    def test_add_project_member(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Member Test",
        )

        membership = store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.OWNER,
        )

        assert membership["id"] is not None
        assert membership["project_id"] == project["id"]
        assert membership["user_id"] == user["id"]
        assert membership["role"] == "owner"

    def test_add_duplicate_member_fails(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Dup Test",
        )

        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.OWNER,
        )

        with pytest.raises(sqlite3.IntegrityError):
            store.add_project_member(
                tenant_id=tenant["id"],
                project_id=project["id"],
                user_id=user["id"],
                role=ProjectRole.EDITOR,
            )

    def test_get_project_membership(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Get Member Test",
        )

        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.EDITOR,
        )

        membership = store.get_project_membership(project["id"], user["id"])

        assert membership is not None
        assert membership["role"] == "editor"

    def test_get_project_membership_not_found(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="No Member",
        )

        membership = store.get_project_membership(project["id"], user["id"])
        assert membership is None

    def test_list_project_members(self, store, tenant_and_user):
        tenant, user1 = tenant_and_user

        # Create second user
        user2 = store.create_user(
            tenant_id=tenant["id"],
            email="user2@example.com",
            password="password",
            role=Role.EDITOR,
        )

        project = store.create_project(
            tenant_id=tenant["id"],
            name="List Members",
        )

        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user1["id"],
            role=ProjectRole.OWNER,
        )
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user2["id"],
            role=ProjectRole.VIEWER,
        )

        members = store.list_project_members(project["id"])

        assert len(members) == 2
        emails = [m["user_email"] for m in members]
        assert "test@example.com" in emails
        assert "user2@example.com" in emails

    def test_list_user_projects(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        p1 = store.create_project(tenant_id=tenant["id"], name="User Project 1")
        p2 = store.create_project(tenant_id=tenant["id"], name="User Project 2")
        store.create_project(tenant_id=tenant["id"], name="Other Project")

        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=p1["id"],
            user_id=user["id"],
            role=ProjectRole.OWNER,
        )
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=p2["id"],
            user_id=user["id"],
            role=ProjectRole.EDITOR,
        )

        projects = store.list_user_projects(user["id"], tenant["id"])

        assert len(projects) == 2
        names = [p["name"] for p in projects]
        assert "User Project 1" in names
        assert "User Project 2" in names
        assert "Other Project" not in names

    def test_update_member_role(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Role Update",
        )

        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.VIEWER,
        )

        result = store.update_project_member_role(
            project_id=project["id"],
            user_id=user["id"],
            new_role=ProjectRole.EDITOR,
        )

        assert result is True

        membership = store.get_project_membership(project["id"], user["id"])
        assert membership["role"] == "editor"

    def test_remove_project_member(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Remove Test",
        )

        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.OWNER,
        )

        result = store.remove_project_member(project["id"], user["id"])
        assert result is True

        membership = store.get_project_membership(project["id"], user["id"])
        assert membership is None

    def test_count_project_owners(self, store, tenant_and_user):
        tenant, user1 = tenant_and_user

        user2 = store.create_user(
            tenant_id=tenant["id"],
            email="owner2@example.com",
            password="password",
            role=Role.EDITOR,
        )
        user3 = store.create_user(
            tenant_id=tenant["id"],
            email="editor@example.com",
            password="password",
            role=Role.EDITOR,
        )

        project = store.create_project(tenant_id=tenant["id"], name="Count Owners")

        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user1["id"],
            role=ProjectRole.OWNER,
        )
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user2["id"],
            role=ProjectRole.OWNER,
        )
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user3["id"],
            role=ProjectRole.EDITOR,
        )

        count = store.count_project_owners(project["id"])
        assert count == 2


class TestProjectRoleHierarchy:
    """Tests for role hierarchy checks."""

    def test_user_has_project_access_viewer(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(tenant_id=tenant["id"], name="Access Test")
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.VIEWER,
        )

        # Viewer can access with viewer requirement
        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.VIEWER
        ) is True

        # Viewer cannot access with editor requirement
        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.EDITOR
        ) is False

        # Viewer cannot access with owner requirement
        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.OWNER
        ) is False

    def test_user_has_project_access_editor(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(tenant_id=tenant["id"], name="Editor Test")
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.EDITOR,
        )

        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.VIEWER
        ) is True
        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.EDITOR
        ) is True
        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.OWNER
        ) is False

    def test_user_has_project_access_owner(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(tenant_id=tenant["id"], name="Owner Test")
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.OWNER,
        )

        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.VIEWER
        ) is True
        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.EDITOR
        ) is True
        assert store.user_has_project_access(
            user["id"], project["id"], min_role=ProjectRole.OWNER
        ) is True

    def test_user_has_project_access_no_role_requirement(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(tenant_id=tenant["id"], name="No Role Test")
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.VIEWER,
        )

        # No min_role = any membership is enough
        assert store.user_has_project_access(user["id"], project["id"]) is True

    def test_user_has_project_access_no_membership(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        project = store.create_project(tenant_id=tenant["id"], name="No Member")

        assert store.user_has_project_access(user["id"], project["id"]) is False


class TestDefaultProjectBackfill:
    """Tests for default project backfill."""

    def test_backfill_creates_project(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        result = store.backfill_default_project(
            tenant_id=tenant["id"],
            created_by_user_id=user["id"],
        )

        assert result["already_existed"] is False
        assert result["project"]["name"] == DEFAULT_PROJECT_NAME
        assert result["members_added"] == 1

    def test_backfill_adds_all_users(self, store, tenant_and_user):
        tenant, user1 = tenant_and_user

        # Create more users
        store.create_user(
            tenant_id=tenant["id"],
            email="user2@example.com",
            password="password",
            role=Role.EDITOR,
        )
        store.create_user(
            tenant_id=tenant["id"],
            email="user3@example.com",
            password="password",
            role=Role.VIEWER,
        )

        result = store.backfill_default_project(tenant_id=tenant["id"])

        assert result["members_added"] == 3

    def test_backfill_users_are_owners(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        result = store.backfill_default_project(tenant_id=tenant["id"])

        membership = store.get_project_membership(
            result["project"]["id"], user["id"]
        )
        assert membership["role"] == "owner"

    def test_backfill_idempotent(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        result1 = store.backfill_default_project(tenant_id=tenant["id"])
        result2 = store.backfill_default_project(tenant_id=tenant["id"])

        assert result1["already_existed"] is False
        assert result2["already_existed"] is True
        assert result2["members_added"] == 0

    def test_backfill_with_existing_default_project(self, store, tenant_and_user):
        tenant, _ = tenant_and_user

        # Manually create default project
        store.create_project(
            tenant_id=tenant["id"],
            name=DEFAULT_PROJECT_NAME,
        )

        result = store.backfill_default_project(tenant_id=tenant["id"])

        assert result["already_existed"] is True


class TestSharesProjectIdMigration:
    """Tests for shares table project_id migration."""

    def test_shares_table_has_project_id(self, store, tenant_and_user):
        tenant, user = tenant_and_user

        # Create a share (the old way, without project_id)
        share = store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="test-run-id",
            created_by=user["id"],
            label="Test Share",
        )

        # The share should exist and work
        assert share["id"] is not None

        # Verify project_id column exists in shares table
        conn = sqlite3.connect(store.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(shares)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "project_id" in columns
        finally:
            conn.close()


class TestDatabaseSchema:
    """Tests for database schema correctness."""

    def test_projects_table_exists(self, store):
        conn = sqlite3.connect(store.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='projects'
            """)
            assert cursor.fetchone() is not None
        finally:
            conn.close()

    def test_project_memberships_table_exists(self, store):
        conn = sqlite3.connect(store.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='project_memberships'
            """)
            assert cursor.fetchone() is not None
        finally:
            conn.close()

    def test_projects_columns(self, store):
        conn = sqlite3.connect(store.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(projects)")
            columns = {row[1] for row in cursor.fetchall()}

            expected = {
                "id", "tenant_id", "name", "created_at", "archived_at",
                "created_by_user_id", "allow_public_shares", "share_max_expiry_hours"
            }
            assert columns == expected
        finally:
            conn.close()

    def test_project_memberships_columns(self, store):
        conn = sqlite3.connect(store.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(project_memberships)")
            columns = {row[1] for row in cursor.fetchall()}

            expected = {
                "id", "tenant_id", "project_id", "user_id", "role", "created_at"
            }
            assert columns == expected
        finally:
            conn.close()

    def test_membership_unique_constraint(self, store, tenant_and_user):
        """Verify (project_id, user_id) uniqueness is enforced."""
        tenant, user = tenant_and_user

        project = store.create_project(
            tenant_id=tenant["id"],
            name="Unique Constraint Test",
        )

        # First membership
        store.add_project_member(
            tenant_id=tenant["id"],
            project_id=project["id"],
            user_id=user["id"],
            role=ProjectRole.OWNER,
        )

        # Second should fail
        with pytest.raises(sqlite3.IntegrityError):
            store.add_project_member(
                tenant_id=tenant["id"],
                project_id=project["id"],
                user_id=user["id"],
                role=ProjectRole.EDITOR,
            )
