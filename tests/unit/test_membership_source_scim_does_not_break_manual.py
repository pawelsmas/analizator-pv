"""
Unit tests for membership source tracking (v4.4.0 PR1).

Tests that SCIM-managed memberships coexist with manual memberships.
"""

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scim_store import ScimStore


def create_test_db(db_path: str) -> None:
    """Create a test database with project_memberships table."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_memberships (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


class TestMembershipSourceMigration:
    """Tests for project_memberships source column migration."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    @pytest.fixture
    def conn(self, store):
        """Get direct database connection."""
        conn = sqlite3.connect(store.db_path)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_project_memberships_table_has_source_column(self, store, conn):
        """project_memberships should have source column after migration."""
        cursor = conn.execute("PRAGMA table_info(project_memberships)")
        columns = {row["name"] for row in cursor.fetchall()}

        assert "source" in columns

    def test_project_memberships_table_has_scim_group_id_column(self, store, conn):
        """project_memberships should have scim_group_id column after migration."""
        cursor = conn.execute("PRAGMA table_info(project_memberships)")
        columns = {row["name"] for row in cursor.fetchall()}

        assert "scim_group_id" in columns

    def test_source_default_is_manual(self, store, conn):
        """New memberships should default to source='manual'."""
        # Insert a membership without specifying source
        conn.execute("""
            INSERT INTO project_memberships (id, project_id, user_id, role, tenant_id)
            VALUES ('mem-1', 'proj-1', 'user-1', 'editor', 'tenant-1')
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT source FROM project_memberships WHERE id = 'mem-1'"
        )
        row = cursor.fetchone()

        assert row["source"] == "manual"

    def test_scim_group_id_default_is_null(self, store, conn):
        """New memberships should have scim_group_id=NULL by default."""
        conn.execute("""
            INSERT INTO project_memberships (id, project_id, user_id, role, tenant_id)
            VALUES ('mem-2', 'proj-1', 'user-2', 'viewer', 'tenant-1')
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT scim_group_id FROM project_memberships WHERE id = 'mem-2'"
        )
        row = cursor.fetchone()

        assert row["scim_group_id"] is None


class TestManualMembershipsUnaffected:
    """Tests that manual memberships work as before."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    @pytest.fixture
    def conn(self, store):
        """Get direct database connection."""
        conn = sqlite3.connect(store.db_path)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_can_create_manual_membership(self, store, conn):
        """Should be able to create manual membership."""
        conn.execute("""
            INSERT INTO project_memberships (id, project_id, user_id, role, tenant_id, source)
            VALUES ('mem-manual', 'proj-1', 'user-1', 'owner', 'tenant-1', 'manual')
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM project_memberships WHERE id = 'mem-manual'"
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["source"] == "manual"
        assert row["role"] == "owner"

    def test_can_create_scim_membership(self, store, conn):
        """Should be able to create SCIM-managed membership."""
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source, scim_group_id)
            VALUES ('mem-scim', 'proj-1', 'user-2', 'editor', 'tenant-1', 'scim', 'group-1')
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM project_memberships WHERE id = 'mem-scim'"
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["source"] == "scim"
        assert row["scim_group_id"] == "group-1"

    def test_manual_and_scim_memberships_coexist(self, store, conn):
        """Manual and SCIM memberships should coexist."""
        # Create manual membership
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source)
            VALUES ('mem-1', 'proj-1', 'user-1', 'owner', 'tenant-1', 'manual')
        """)

        # Create SCIM membership for same user on different project
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source, scim_group_id)
            VALUES ('mem-2', 'proj-2', 'user-1', 'viewer', 'tenant-1', 'scim', 'group-1')
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM project_memberships WHERE user_id = 'user-1' ORDER BY project_id"
        )
        rows = cursor.fetchall()

        assert len(rows) == 2
        assert rows[0]["source"] == "manual"
        assert rows[0]["scim_group_id"] is None
        assert rows[1]["source"] == "scim"
        assert rows[1]["scim_group_id"] == "group-1"

    def test_query_manual_memberships_only(self, store, conn):
        """Should be able to query only manual memberships."""
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source)
            VALUES ('mem-1', 'proj-1', 'user-1', 'owner', 'tenant-1', 'manual')
        """)
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source, scim_group_id)
            VALUES ('mem-2', 'proj-1', 'user-2', 'viewer', 'tenant-1', 'scim', 'group-1')
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM project_memberships WHERE source = 'manual'"
        )
        rows = cursor.fetchall()

        assert len(rows) == 1
        assert rows[0]["user_id"] == "user-1"

    def test_query_scim_memberships_only(self, store, conn):
        """Should be able to query only SCIM memberships."""
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source)
            VALUES ('mem-1', 'proj-1', 'user-1', 'owner', 'tenant-1', 'manual')
        """)
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source, scim_group_id)
            VALUES ('mem-2', 'proj-1', 'user-2', 'viewer', 'tenant-1', 'scim', 'group-1')
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM project_memberships WHERE source = 'scim'"
        )
        rows = cursor.fetchall()

        assert len(rows) == 1
        assert rows[0]["user_id"] == "user-2"

    def test_delete_scim_memberships_by_group(self, store, conn):
        """Should be able to delete SCIM memberships by group without affecting manual."""
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source)
            VALUES ('mem-manual', 'proj-1', 'user-1', 'owner', 'tenant-1', 'manual')
        """)
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source, scim_group_id)
            VALUES ('mem-scim-1', 'proj-1', 'user-2', 'editor', 'tenant-1', 'scim', 'group-1')
        """)
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source, scim_group_id)
            VALUES ('mem-scim-2', 'proj-1', 'user-3', 'viewer', 'tenant-1', 'scim', 'group-1')
        """)
        conn.commit()

        # Delete all SCIM memberships for group-1
        conn.execute(
            "DELETE FROM project_memberships WHERE scim_group_id = 'group-1'"
        )
        conn.commit()

        cursor = conn.execute("SELECT * FROM project_memberships")
        rows = cursor.fetchall()

        assert len(rows) == 1
        assert rows[0]["source"] == "manual"
        assert rows[0]["user_id"] == "user-1"

    def test_update_manual_membership_preserves_source(self, store, conn):
        """Updating manual membership should preserve source."""
        conn.execute("""
            INSERT INTO project_memberships
            (id, project_id, user_id, role, tenant_id, source)
            VALUES ('mem-1', 'proj-1', 'user-1', 'editor', 'tenant-1', 'manual')
        """)
        conn.commit()

        # Update role
        conn.execute("""
            UPDATE project_memberships SET role = 'owner' WHERE id = 'mem-1'
        """)
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM project_memberships WHERE id = 'mem-1'"
        )
        row = cursor.fetchone()

        assert row["role"] == "owner"
        assert row["source"] == "manual"


class TestScimUsersCRUD:
    """Tests for SCIM users CRUD operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_create_scim_user(self, store):
        """Should be able to create SCIM user."""
        result = store.create_scim_user(
            tenant_id="tenant-1",
            user_id="user-1",
            user_name="john.doe@example.com",
            external_id="ext-user-1"
        )

        assert result is not None
        assert "id" in result
        assert result["tenant_id"] == "tenant-1"
        assert result["user_id"] == "user-1"

    def test_get_scim_user(self, store):
        """Should be able to get SCIM user by ID."""
        created = store.create_scim_user(
            "tenant-1", "user-1", "john@example.com", "ext-1"
        )

        user = store.get_scim_user(created["id"])

        assert user is not None
        assert user["user_id"] == "user-1"
        assert user["external_id"] == "ext-1"
        assert user["user_name"] == "john@example.com"

    def test_get_scim_user_by_user_name(self, store):
        """Should be able to get SCIM user by userName."""
        store.create_scim_user("tenant-1", "user-1", "john@example.com", "ext-user-1")

        user = store.get_scim_user_by_user_name("tenant-1", "john@example.com")

        assert user is not None
        assert user["user_id"] == "user-1"

    def test_list_scim_users(self, store):
        """Should be able to list SCIM users for tenant."""
        store.create_scim_user("tenant-1", "user-1", "john@example.com", "ext-1")
        store.create_scim_user("tenant-1", "user-2", "jane@example.com", "ext-2")
        store.create_scim_user("tenant-2", "user-3", "bob@example.com", "ext-3")

        users, total = store.list_scim_users("tenant-1")

        assert len(users) == 2
        assert total == 2

    def test_update_scim_user(self, store):
        """Should be able to update SCIM user."""
        created = store.create_scim_user(
            "tenant-1", "user-1", "john@example.com", "old-ext"
        )

        result = store.update_scim_user(created["id"], external_id="new-ext")

        assert result is not None
        assert result["external_id"] == "new-ext"

    def test_delete_scim_user(self, store):
        """Should be able to delete SCIM user."""
        created = store.create_scim_user(
            "tenant-1", "user-1", "john@example.com", "ext-1"
        )

        result = store.delete_scim_user(created["id"])
        assert result is True

        user = store.get_scim_user(created["id"])
        assert user is None


class TestScimGroupsCRUD:
    """Tests for SCIM groups CRUD operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_create_scim_group(self, store):
        """Should be able to create SCIM group."""
        result = store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering",
            external_id="eng-group"
        )

        assert result is not None
        assert "id" in result
        assert result["display_name"] == "Engineering"

    def test_get_scim_group(self, store):
        """Should be able to get SCIM group by ID."""
        created = store.create_scim_group("tenant-1", "Engineering", "eng")

        group = store.get_scim_group(created["id"])

        assert group is not None
        assert group["display_name"] == "Engineering"
        assert group["external_id"] == "eng"

    def test_list_scim_groups(self, store):
        """Should be able to list SCIM groups for tenant."""
        store.create_scim_group("tenant-1", "Engineering", "eng")
        store.create_scim_group("tenant-1", "Marketing", "mkt")
        store.create_scim_group("tenant-2", "Sales", "sales")

        groups, total = store.list_scim_groups("tenant-1")

        assert len(groups) == 2
        assert total == 2

    def test_update_scim_group(self, store):
        """Should be able to update SCIM group."""
        created = store.create_scim_group("tenant-1", "Engineering", "eng")

        result = store.update_scim_group(
            created["id"], display_name="Platform Engineering"
        )

        assert result is not None
        assert result["display_name"] == "Platform Engineering"

    def test_delete_scim_group(self, store):
        """Should be able to delete SCIM group."""
        created = store.create_scim_group("tenant-1", "Engineering", "eng")

        result = store.delete_scim_group(created["id"])
        assert result is True

        group = store.get_scim_group(created["id"])
        assert group is None


class TestScimGroupMembers:
    """Tests for SCIM group membership operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_add_group_member(self, store):
        """Should be able to add member to group."""
        group = store.create_scim_group("tenant-1", "Engineering", "eng")
        user = store.create_scim_user("tenant-1", "user-1", "john@example.com", "ext-1")

        result = store.add_group_member(group["id"], user["id"])
        assert result is True

    def test_get_group_members(self, store):
        """Should be able to get group members."""
        group = store.create_scim_group("tenant-1", "Engineering", "eng")
        user1 = store.create_scim_user("tenant-1", "user-1", "john@example.com", "ext-1")
        user2 = store.create_scim_user("tenant-1", "user-2", "jane@example.com", "ext-2")

        store.add_group_member(group["id"], user1["id"])
        store.add_group_member(group["id"], user2["id"])

        members = store.get_group_members(group["id"])

        assert len(members) == 2

    def test_remove_group_member(self, store):
        """Should be able to remove member from group."""
        group = store.create_scim_group("tenant-1", "Engineering", "eng")
        user = store.create_scim_user("tenant-1", "user-1", "john@example.com", "ext-1")

        store.add_group_member(group["id"], user["id"])

        result = store.remove_group_member(group["id"], user["id"])
        assert result is True

        members = store.get_group_members(group["id"])
        assert len(members) == 0

    def test_set_group_members_replaces_all(self, store):
        """set_group_members should replace all members."""
        group = store.create_scim_group("tenant-1", "Engineering", "eng")
        user1 = store.create_scim_user("tenant-1", "user-1", "john@example.com", "ext-1")
        user2 = store.create_scim_user("tenant-1", "user-2", "jane@example.com", "ext-2")
        user3 = store.create_scim_user("tenant-1", "user-3", "bob@example.com", "ext-3")

        # Add initial members
        store.add_group_member(group["id"], user1["id"])
        store.add_group_member(group["id"], user2["id"])

        # Replace with new set
        store.set_group_members(group["id"], [user2["id"], user3["id"]])

        members = store.get_group_members(group["id"])
        # get_group_members returns scim_user records with "id" field
        member_ids = [m["id"] for m in members]

        assert len(members) == 2
        assert user1["id"] not in member_ids
        assert user2["id"] in member_ids
        assert user3["id"] in member_ids


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
