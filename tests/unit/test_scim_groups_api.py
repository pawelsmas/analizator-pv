"""
Unit tests for SCIM Groups API (v4.4.0 PR5).

Tests SCIM group CRUD operations and member management.
"""

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scim_store import ScimStore
from scim_groups_api import parse_filter, format_group_response, format_members


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


class TestParseFilter:
    """Tests for SCIM filter parsing."""

    def test_parse_display_name_eq(self):
        """Should parse displayName eq filter."""
        result = parse_filter('displayName eq "Engineering"')
        assert result is not None
        assert result["field"] == "display_name"
        assert result["value"] == "Engineering"

    def test_parse_external_id_eq(self):
        """Should parse externalId eq filter."""
        result = parse_filter('externalId eq "group-123"')
        assert result is not None
        assert result["field"] == "external_id"
        assert result["value"] == "group-123"

    def test_parse_invalid_filter(self):
        """Should return None for invalid filter."""
        result = parse_filter('invalid filter')
        assert result is None

    def test_parse_unsupported_field(self):
        """Should return None for unsupported field."""
        result = parse_filter('members eq "value"')
        assert result is None

    def test_parse_none(self):
        """Should return None when filter is None."""
        result = parse_filter(None)
        assert result is None


class TestFormatMembers:
    """Tests for member formatting."""

    def test_format_single_member(self):
        """Should format single member."""
        members = [{"id": "user-1", "display_name": "John Doe", "user_name": "jdoe"}]
        result = format_members(members)

        assert len(result) == 1
        assert result[0]["value"] == "user-1"
        assert result[0]["display"] == "John Doe"
        assert result[0]["type"] == "User"
        assert "$ref" in result[0]

    def test_format_member_fallback_to_username(self):
        """Should use user_name if display_name is missing."""
        members = [{"id": "user-1", "user_name": "jdoe"}]
        result = format_members(members)

        assert result[0]["display"] == "jdoe"

    def test_format_empty_members(self):
        """Should return empty list for no members."""
        result = format_members([])
        assert result == []


class TestFormatGroupResponse:
    """Tests for group response formatting."""

    def test_format_group_without_members(self):
        """Should format group without members."""
        group = {
            "id": "group-123",
            "tenant_id": "tenant-1",
            "display_name": "Engineering",
            "external_id": "ext-123",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z"
        }
        result = format_group_response(group)

        assert result["id"] == "group-123"
        assert result["displayName"] == "Engineering"
        assert result["externalId"] == "ext-123"
        assert "members" not in result

    def test_format_group_with_members(self):
        """Should format group with members."""
        group = {"id": "group-123", "display_name": "Engineering"}
        members = [{"id": "user-1", "display_name": "John Doe"}]

        result = format_group_response(group, members)

        assert "members" in result
        assert len(result["members"]) == 1

    def test_format_group_has_schemas(self):
        """Should include SCIM schema."""
        group = {"id": "group-123", "display_name": "Engineering"}
        result = format_group_response(group)

        assert "schemas" in result
        assert "urn:ietf:params:scim:schemas:core:2.0:Group" in result["schemas"]

    def test_format_group_has_meta(self):
        """Should include meta section."""
        group = {"id": "group-123", "display_name": "Engineering"}
        result = format_group_response(group)

        assert "meta" in result
        assert result["meta"]["resourceType"] == "Group"


class TestScimGroupCreate:
    """Tests for SCIM group creation."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_create_group_minimal(self, store):
        """Should create group with minimal fields."""
        group = store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering"
        )

        assert group["id"] is not None
        assert group["display_name"] == "Engineering"
        assert group["tenant_id"] == "tenant-1"

    def test_create_group_with_external_id(self, store):
        """Should create group with externalId."""
        group = store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering",
            external_id="group-123"
        )

        assert group["external_id"] == "group-123"

    def test_create_duplicate_display_name_fails(self, store):
        """Should fail for duplicate displayName in same tenant."""
        store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")

        with pytest.raises(Exception) as exc_info:
            store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")

        assert "UNIQUE constraint" in str(exc_info.value)

    def test_create_same_display_name_different_tenants(self, store):
        """Should allow same displayName in different tenants."""
        group1 = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        group2 = store.create_scim_group(tenant_id="tenant-2", display_name="Engineering")

        assert group1["id"] != group2["id"]


class TestScimGroupGet:
    """Tests for getting SCIM groups."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_get_group_by_id(self, store):
        """Should get group by ID."""
        created = store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering"
        )

        group = store.get_scim_group(created["id"])

        assert group is not None
        assert group["display_name"] == "Engineering"

    def test_get_nonexistent_group(self, store):
        """Should return None for nonexistent group."""
        group = store.get_scim_group("nonexistent")
        assert group is None

    def test_get_group_by_display_name(self, store):
        """Should get group by displayName."""
        store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering"
        )

        group = store.get_scim_group_by_display_name("tenant-1", "Engineering")

        assert group is not None
        assert group["display_name"] == "Engineering"


class TestScimGroupList:
    """Tests for listing SCIM groups."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_list_empty(self, store):
        """Should return empty list when no groups."""
        groups = store.list_scim_groups("tenant-1")
        assert groups == []

    def test_list_groups(self, store):
        """Should list all groups for tenant."""
        store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        store.create_scim_group(tenant_id="tenant-1", display_name="Marketing")
        store.create_scim_group(tenant_id="tenant-2", display_name="Sales")

        groups = store.list_scim_groups("tenant-1")

        assert len(groups) == 2
        names = [g["display_name"] for g in groups]
        assert "Engineering" in names
        assert "Marketing" in names
        assert "Sales" not in names

    def test_list_with_pagination(self, store):
        """Should paginate results."""
        for i in range(5):
            store.create_scim_group(tenant_id="tenant-1", display_name=f"Group{i}")

        page1 = store.list_scim_groups("tenant-1", offset=0, limit=2)
        page2 = store.list_scim_groups("tenant-1", offset=2, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2

    def test_count_groups(self, store):
        """Should count groups for tenant."""
        store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        store.create_scim_group(tenant_id="tenant-1", display_name="Marketing")
        store.create_scim_group(tenant_id="tenant-2", display_name="Sales")

        count = store.count_scim_groups("tenant-1")

        assert count == 2


class TestScimGroupFind:
    """Tests for finding SCIM groups by field."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_find_by_display_name(self, store):
        """Should find groups by displayName."""
        store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        store.create_scim_group(tenant_id="tenant-1", display_name="Marketing")

        groups = store.find_scim_groups("tenant-1", "display_name", "Engineering")

        assert len(groups) == 1
        assert groups[0]["display_name"] == "Engineering"

    def test_find_by_external_id(self, store):
        """Should find groups by externalId."""
        store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering",
            external_id="ext-123"
        )

        groups = store.find_scim_groups("tenant-1", "external_id", "ext-123")

        assert len(groups) == 1
        assert groups[0]["external_id"] == "ext-123"

    def test_find_no_match(self, store):
        """Should return empty list when no match."""
        store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")

        groups = store.find_scim_groups("tenant-1", "display_name", "NoMatch")

        assert groups == []


class TestScimGroupUpdate:
    """Tests for updating SCIM groups."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_update_display_name(self, store):
        """Should update displayName."""
        group = store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering"
        )

        store.update_scim_group(group["id"], {"display_name": "Product"})

        updated = store.get_scim_group(group["id"])
        assert updated["display_name"] == "Product"

    def test_update_external_id(self, store):
        """Should update externalId."""
        group = store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering"
        )

        store.update_scim_group(group["id"], {"external_id": "new-ext-id"})

        updated = store.get_scim_group(group["id"])
        assert updated["external_id"] == "new-ext-id"

    def test_update_nonexistent_returns_false(self, store):
        """Should return False for nonexistent group."""
        result = store.update_scim_group("nonexistent", {"display_name": "Test"})
        assert result is False


class TestScimGroupDelete:
    """Tests for deleting SCIM groups."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_delete_group(self, store):
        """Should delete group."""
        group = store.create_scim_group(
            tenant_id="tenant-1",
            display_name="Engineering"
        )

        result = store.delete_scim_group(group["id"])

        assert result is True
        assert store.get_scim_group(group["id"]) is None

    def test_delete_nonexistent_returns_false(self, store):
        """Should return False for nonexistent group."""
        result = store.delete_scim_group("nonexistent")
        assert result is False


class TestScimGroupMembers:
    """Tests for SCIM group member management."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_add_member(self, store):
        """Should add member to group."""
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")

        result = store.add_group_member(group["id"], user["id"])

        assert result is True

        members = store.get_group_members(group["id"])
        assert len(members) == 1
        assert members[0]["id"] == user["id"]

    def test_add_duplicate_member_ignored(self, store):
        """Should ignore duplicate member adds."""
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")

        store.add_group_member(group["id"], user["id"])
        result = store.add_group_member(group["id"], user["id"])

        assert result is False  # No row inserted

        members = store.get_group_members(group["id"])
        assert len(members) == 1

    def test_remove_member(self, store):
        """Should remove member from group."""
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")
        store.add_group_member(group["id"], user["id"])

        result = store.remove_group_member(group["id"], user["id"])

        assert result is True
        assert store.get_group_members(group["id"]) == []

    def test_remove_nonexistent_member(self, store):
        """Should return False when removing nonexistent member."""
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")

        result = store.remove_group_member(group["id"], "nonexistent")

        assert result is False

    def test_set_group_members(self, store):
        """Should replace all members."""
        group = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        user1 = store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        user2 = store.create_scim_user(tenant_id="tenant-1", user_name="user2")
        user3 = store.create_scim_user(tenant_id="tenant-1", user_name="user3")

        # Initially add user1 and user2
        store.add_group_member(group["id"], user1["id"])
        store.add_group_member(group["id"], user2["id"])

        # Replace with user2 and user3
        added, removed = store.set_group_members(group["id"], [user2["id"], user3["id"]])

        assert added == 1  # user3 added
        assert removed == 1  # user1 removed

        members = store.get_group_members(group["id"])
        member_ids = [m["id"] for m in members]
        assert user1["id"] not in member_ids
        assert user2["id"] in member_ids
        assert user3["id"] in member_ids

    def test_get_user_groups(self, store):
        """Should get all groups a user belongs to."""
        group1 = store.create_scim_group(tenant_id="tenant-1", display_name="Engineering")
        group2 = store.create_scim_group(tenant_id="tenant-1", display_name="Marketing")
        user = store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")

        store.add_group_member(group1["id"], user["id"])
        store.add_group_member(group2["id"], user["id"])

        groups = store.get_user_groups(user["id"])

        assert len(groups) == 2
        names = [g["display_name"] for g in groups]
        assert "Engineering" in names
        assert "Marketing" in names


class TestTenantIsolation:
    """Tests for tenant isolation in group operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_list_isolated_by_tenant(self, store):
        """Should list only groups from specified tenant."""
        store.create_scim_group(tenant_id="tenant-1", display_name="T1 Group")
        store.create_scim_group(tenant_id="tenant-2", display_name="T2 Group")

        t1_groups = store.list_scim_groups("tenant-1")
        t2_groups = store.list_scim_groups("tenant-2")

        assert len(t1_groups) == 1
        assert t1_groups[0]["display_name"] == "T1 Group"
        assert len(t2_groups) == 1
        assert t2_groups[0]["display_name"] == "T2 Group"

    def test_count_isolated_by_tenant(self, store):
        """Should count only groups from specified tenant."""
        store.create_scim_group(tenant_id="tenant-1", display_name="Group1")
        store.create_scim_group(tenant_id="tenant-1", display_name="Group2")
        store.create_scim_group(tenant_id="tenant-2", display_name="Group3")

        assert store.count_scim_groups("tenant-1") == 2
        assert store.count_scim_groups("tenant-2") == 1


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
