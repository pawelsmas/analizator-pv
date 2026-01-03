"""
Unit tests for Group Sync Engine (v4.4.0 PR6).

Tests SCIM group → project membership synchronization.
"""

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scim_store import ScimStore
from group_sync_engine import GroupSyncEngine


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
            source TEXT NOT NULL DEFAULT 'manual',
            scim_group_id TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_memberships_tenant ON project_memberships(tenant_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_memberships_project ON project_memberships(project_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_memberships_user ON project_memberships(user_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_memberships_source ON project_memberships(source)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_memberships_scim_group ON project_memberships(scim_group_id)
    """)
    conn.commit()
    conn.close()


class TestSyncGroup:
    """Tests for syncing a single SCIM group."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create test database path."""
        db_path = tmp_path / "test_sync.db"
        create_test_db(str(db_path))
        return str(db_path)

    @pytest.fixture
    def store(self, db_path):
        """Create a ScimStore."""
        return ScimStore(db_path)

    @pytest.fixture
    def engine(self, db_path):
        """Create a GroupSyncEngine."""
        return GroupSyncEngine(db_path)

    def test_sync_group_no_mappings(self, store, engine):
        """Should return zero changes when no mappings exist."""
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")

        result = engine.sync_group(group["id"])

        assert result["group_id"] == group["id"]
        assert result["mappings_processed"] == 0
        assert result["members_added"] == 0
        assert result["members_removed"] == 0
        assert result["errors"] == []

    def test_sync_group_adds_members(self, store, engine):
        """Should add memberships when users are in group."""
        # Create group with users
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user1 = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        user2 = store.create_scim_user(tenant_id="tenant-1", user_name="user2")
        store.add_group_member(group["id"], user1["id"])
        store.add_group_member(group["id"], user2["id"])

        # Create mapping
        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-1",
            role="viewer"
        )

        result = engine.sync_group(group["id"])

        assert result["mappings_processed"] == 1
        assert result["members_added"] == 2
        assert result["members_removed"] == 0

        # Verify memberships created
        memberships = engine.get_scim_memberships("tenant-1", project_id="project-1")
        assert len(memberships) == 2

    def test_sync_group_removes_members(self, store, engine):
        """Should remove memberships when users are removed from group."""
        # Create group with user
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        store.add_group_member(group["id"], user["id"])

        # Create mapping
        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-1",
            role="viewer"
        )

        # Initial sync
        engine.sync_group(group["id"])

        # Remove user from group
        store.remove_group_member(group["id"], user["id"])

        # Sync again
        result = engine.sync_group(group["id"])

        assert result["members_removed"] == 1

        # Verify membership removed
        memberships = engine.get_scim_memberships("tenant-1", project_id="project-1")
        assert len(memberships) == 0

    def test_sync_group_nonexistent(self, engine):
        """Should return error for nonexistent group."""
        result = engine.sync_group("nonexistent")

        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]

    def test_sync_preserves_manual_memberships(self, store, engine, db_path):
        """Should not remove manual memberships."""
        # Create group
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")

        # Create mapping
        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-1",
            role="viewer"
        )

        # Add manual membership directly
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO project_memberships (id, tenant_id, project_id, user_id, role, source, created_at)
            VALUES ('manual-1', 'tenant-1', 'project-1', 'manual-user', 'admin', 'manual', datetime('now'))
            """
        )
        conn.commit()
        conn.close()

        # Sync group (which has no users)
        engine.sync_group(group["id"])

        # Manual membership should still exist
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM project_memberships WHERE id = 'manual-1'")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row["source"] == "manual"


class TestSyncAllGroups:
    """Tests for syncing all groups for a tenant."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create test database path."""
        db_path = tmp_path / "test_sync.db"
        create_test_db(str(db_path))
        return str(db_path)

    @pytest.fixture
    def store(self, db_path):
        """Create a ScimStore."""
        return ScimStore(db_path)

    @pytest.fixture
    def engine(self, db_path):
        """Create a GroupSyncEngine."""
        return GroupSyncEngine(db_path)

    def test_sync_all_groups_empty(self, engine):
        """Should return zero when no groups exist."""
        result = engine.sync_all_groups("tenant-1")

        assert result["groups_processed"] == 0
        assert result["members_added"] == 0

    def test_sync_all_groups_multiple(self, store, engine):
        """Should sync all groups with mappings."""
        # Create two groups with users and mappings
        group1 = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        group2 = store.create_scim_group(tenant_id="tenant-1", display_name="Marketing")
        user1 = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        user2 = store.create_scim_user(tenant_id="tenant-1", user_name="user2")

        store.add_group_member(group1["id"], user1["id"])
        store.add_group_member(group2["id"], user2["id"])

        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group1["id"],
            project_id="project-1",
            role="viewer"
        )
        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group2["id"],
            project_id="project-2",
            role="editor"
        )

        result = engine.sync_all_groups("tenant-1")

        assert result["groups_processed"] == 2
        assert result["mappings_processed"] == 2
        assert result["members_added"] == 2


class TestSyncUser:
    """Tests for syncing a specific user's memberships."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create test database path."""
        db_path = tmp_path / "test_sync.db"
        create_test_db(str(db_path))
        return str(db_path)

    @pytest.fixture
    def store(self, db_path):
        """Create a ScimStore."""
        return ScimStore(db_path)

    @pytest.fixture
    def engine(self, db_path):
        """Create a GroupSyncEngine."""
        return GroupSyncEngine(db_path)

    def test_sync_user_multiple_groups(self, store, engine):
        """Should sync user across all their groups."""
        # Create user in multiple groups
        user = store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")
        group1 = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        group2 = store.create_scim_group(tenant_id="tenant-1", display_name="DevOps")

        store.add_group_member(group1["id"], user["id"])
        store.add_group_member(group2["id"], user["id"])

        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group1["id"],
            project_id="project-1",
            role="viewer"
        )
        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group2["id"],
            project_id="project-2",
            role="admin"
        )

        result = engine.sync_user(user["id"])

        assert result["groups_synced"] == 2
        assert result["memberships_added"] >= 1

    def test_sync_user_nonexistent(self, engine):
        """Should return error for nonexistent user."""
        result = engine.sync_user("nonexistent")

        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]


class TestRevokeMemberships:
    """Tests for revoking SCIM memberships."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create test database path."""
        db_path = tmp_path / "test_sync.db"
        create_test_db(str(db_path))
        return str(db_path)

    @pytest.fixture
    def store(self, db_path):
        """Create a ScimStore."""
        return ScimStore(db_path)

    @pytest.fixture
    def engine(self, db_path):
        """Create a GroupSyncEngine."""
        return GroupSyncEngine(db_path)

    def test_revoke_all_for_group(self, store, engine):
        """Should revoke all memberships for a group."""
        # Setup
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        store.add_group_member(group["id"], user["id"])

        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-1",
            role="viewer"
        )
        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-2",
            role="editor"
        )

        engine.sync_group(group["id"])

        # Revoke all
        removed = engine.revoke_scim_memberships("tenant-1", group["id"])

        assert removed == 2
        assert engine.get_scim_memberships("tenant-1", project_id="project-1") == []
        assert engine.get_scim_memberships("tenant-1", project_id="project-2") == []

    def test_revoke_for_specific_project(self, store, engine):
        """Should revoke memberships only for specific project."""
        # Setup
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        store.add_group_member(group["id"], user["id"])

        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-1",
            role="viewer"
        )
        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-2",
            role="editor"
        )

        engine.sync_group(group["id"])

        # Revoke only project-1
        removed = engine.revoke_scim_memberships("tenant-1", group["id"], project_id="project-1")

        assert removed == 1
        assert engine.get_scim_memberships("tenant-1", project_id="project-1") == []
        assert len(engine.get_scim_memberships("tenant-1", project_id="project-2")) == 1


class TestGetSyncStatus:
    """Tests for sync status reporting."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create test database path."""
        db_path = tmp_path / "test_sync.db"
        create_test_db(str(db_path))
        return str(db_path)

    @pytest.fixture
    def store(self, db_path):
        """Create a ScimStore."""
        return ScimStore(db_path)

    @pytest.fixture
    def engine(self, db_path):
        """Create a GroupSyncEngine."""
        return GroupSyncEngine(db_path)

    def test_status_empty_tenant(self, engine):
        """Should return zeros for empty tenant."""
        status = engine.get_sync_status("tenant-1")

        assert status["tenant_id"] == "tenant-1"
        assert status["scim_groups"] == 0
        assert status["enabled_mappings"] == 0
        assert status["scim_memberships"] == 0
        assert status["manual_memberships"] == 0

    def test_status_with_data(self, store, engine, db_path):
        """Should return correct counts."""
        # Create groups and mappings
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        store.add_group_member(group["id"], user["id"])

        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group["id"],
            project_id="project-1",
            role="viewer"
        )

        engine.sync_group(group["id"])

        # Add manual membership
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO project_memberships (id, tenant_id, project_id, user_id, role, source, created_at)
            VALUES ('manual-1', 'tenant-1', 'project-2', 'manual-user', 'admin', 'manual', datetime('now'))
            """
        )
        conn.commit()
        conn.close()

        status = engine.get_sync_status("tenant-1")

        assert status["scim_groups"] == 1
        assert status["enabled_mappings"] == 1
        assert status["scim_memberships"] == 1
        assert status["manual_memberships"] == 1


class TestTenantIsolation:
    """Tests for tenant isolation in sync operations."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create test database path."""
        db_path = tmp_path / "test_sync.db"
        create_test_db(str(db_path))
        return str(db_path)

    @pytest.fixture
    def store(self, db_path):
        """Create a ScimStore."""
        return ScimStore(db_path)

    @pytest.fixture
    def engine(self, db_path):
        """Create a GroupSyncEngine."""
        return GroupSyncEngine(db_path)

    def test_sync_isolated_by_tenant(self, store, engine):
        """Should only sync groups for specified tenant."""
        # Create groups in different tenants
        group1 = store.create_scim_group(tenant_id="tenant-1", display_name="T1 Group")
        group2 = store.create_scim_group(tenant_id="tenant-2", display_name="T2 Group")

        user1 = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        user2 = store.create_scim_user(tenant_id="tenant-2", user_name="user2")

        store.add_group_member(group1["id"], user1["id"])
        store.add_group_member(group2["id"], user2["id"])

        store.create_group_project_mapping(
            tenant_id="tenant-1",
            scim_group_id=group1["id"],
            project_id="project-1",
            role="viewer"
        )
        store.create_group_project_mapping(
            tenant_id="tenant-2",
            scim_group_id=group2["id"],
            project_id="project-2",
            role="viewer"
        )

        # Sync only tenant-1
        result = engine.sync_all_groups("tenant-1")

        assert result["groups_processed"] == 1
        assert result["members_added"] == 1

        # Verify only tenant-1 memberships created
        t1_memberships = engine.get_scim_memberships("tenant-1")
        t2_memberships = engine.get_scim_memberships("tenant-2")

        assert len(t1_memberships) == 1
        assert len(t2_memberships) == 0


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
