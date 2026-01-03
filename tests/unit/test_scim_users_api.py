"""
Unit tests for SCIM Users API (v4.4.0 PR4).

Tests SCIM user CRUD operations, filter, and pagination.
"""

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scim_store import ScimStore
from scim_users_api import parse_filter, format_user_response, format_emails


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

    def test_parse_username_eq(self):
        """Should parse userName eq filter."""
        result = parse_filter('userName eq "jdoe"')
        assert result is not None
        assert result["field"] == "user_name"
        assert result["value"] == "jdoe"

    def test_parse_username_eq_single_quotes(self):
        """Should parse userName eq with single quotes."""
        result = parse_filter("userName eq 'jdoe'")
        assert result is not None
        assert result["field"] == "user_name"
        assert result["value"] == "jdoe"

    def test_parse_external_id_eq(self):
        """Should parse externalId eq filter."""
        result = parse_filter('externalId eq "12345"')
        assert result is not None
        assert result["field"] == "external_id"
        assert result["value"] == "12345"

    def test_parse_email_eq(self):
        """Should parse email eq filter."""
        result = parse_filter('email eq "user@example.com"')
        assert result is not None
        assert result["field"] == "email"
        assert result["value"] == "user@example.com"

    def test_parse_invalid_filter(self):
        """Should return None for invalid filter."""
        result = parse_filter('invalid filter')
        assert result is None

    def test_parse_unsupported_field(self):
        """Should return None for unsupported field."""
        result = parse_filter('displayName eq "John"')
        assert result is None

    def test_parse_none(self):
        """Should return None when filter is None."""
        result = parse_filter(None)
        assert result is None

    def test_parse_empty(self):
        """Should return None when filter is empty."""
        result = parse_filter("")
        assert result is None

    def test_parse_case_insensitive_eq(self):
        """Should parse EQ case-insensitively."""
        result = parse_filter('userName EQ "jdoe"')
        assert result is not None
        assert result["field"] == "user_name"


class TestFormatEmails:
    """Tests for email formatting."""

    def test_format_single_email(self):
        """Should format single email as list."""
        result = format_emails("user@example.com")
        assert len(result) == 1
        assert result[0]["value"] == "user@example.com"
        assert result[0]["type"] == "work"
        assert result[0]["primary"] is True

    def test_format_none_email(self):
        """Should return empty list for None email."""
        result = format_emails(None)
        assert result == []

    def test_format_empty_email(self):
        """Should return empty list for empty email."""
        result = format_emails("")
        assert result == []


class TestFormatUserResponse:
    """Tests for user response formatting."""

    def test_format_full_user(self):
        """Should format user with all fields."""
        user = {
            "id": "user-123",
            "tenant_id": "tenant-1",
            "external_id": "ext-123",
            "user_name": "jdoe",
            "email": "jdoe@example.com",
            "display_name": "John Doe",
            "given_name": "John",
            "family_name": "Doe",
            "active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z"
        }
        result = format_user_response(user)

        assert result["id"] == "user-123"
        assert result["userName"] == "jdoe"
        assert result["externalId"] == "ext-123"
        assert result["displayName"] == "John Doe"
        assert result["name"]["givenName"] == "John"
        assert result["name"]["familyName"] == "Doe"
        assert result["active"] is True
        assert len(result["emails"]) == 1
        assert result["emails"][0]["value"] == "jdoe@example.com"

    def test_format_user_minimal(self):
        """Should format user with minimal fields."""
        user = {
            "id": "user-123",
            "user_name": "jdoe",
            "created_at": "2024-01-01T00:00:00Z"
        }
        result = format_user_response(user)

        assert result["id"] == "user-123"
        assert result["userName"] == "jdoe"
        assert result["emails"] == []

    def test_format_user_has_schemas(self):
        """Should include SCIM schema."""
        user = {"id": "user-123", "user_name": "jdoe"}
        result = format_user_response(user)

        assert "schemas" in result
        assert "urn:ietf:params:scim:schemas:core:2.0:User" in result["schemas"]

    def test_format_user_has_meta(self):
        """Should include meta section."""
        user = {
            "id": "user-123",
            "user_name": "jdoe",
            "created_at": "2024-01-01T00:00:00Z"
        }
        result = format_user_response(user)

        assert "meta" in result
        assert result["meta"]["resourceType"] == "User"
        assert "location" in result["meta"]


class TestScimUserCreate:
    """Tests for SCIM user creation."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_create_user_minimal(self, store):
        """Should create user with minimal fields."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe"
        )

        assert user["id"] is not None
        assert user["user_name"] == "jdoe"
        assert user["tenant_id"] == "tenant-1"
        assert user["active"] is True

    def test_create_user_full(self, store):
        """Should create user with all fields."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            external_id="ext-123",
            email="jdoe@example.com",
            display_name="John Doe",
            given_name="John",
            family_name="Doe",
            active=True
        )

        assert user["user_name"] == "jdoe"
        assert user["external_id"] == "ext-123"
        assert user["email"] == "jdoe@example.com"
        assert user["display_name"] == "John Doe"
        assert user["given_name"] == "John"
        assert user["family_name"] == "Doe"
        assert user["active"] is True

    def test_create_user_inactive(self, store):
        """Should create inactive user."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            active=False
        )

        assert user["active"] is False

    def test_create_user_username_lowercase(self, store):
        """Should store userName in lowercase."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="JDoe@Example.COM"
        )

        assert user["user_name"] == "jdoe@example.com"

    def test_create_duplicate_username_fails(self, store):
        """Should fail for duplicate userName in same tenant."""
        store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")

        with pytest.raises(Exception) as exc_info:
            store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")

        assert "UNIQUE constraint" in str(exc_info.value)

    def test_create_same_username_different_tenants(self, store):
        """Should allow same userName in different tenants."""
        user1 = store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")
        user2 = store.create_scim_user(tenant_id="tenant-2", user_name="jdoe")

        assert user1["id"] != user2["id"]


class TestScimUserGet:
    """Tests for getting SCIM users."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_get_user_by_id(self, store):
        """Should get user by ID."""
        created = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            display_name="John Doe"
        )

        user = store.get_scim_user(created["id"])

        assert user is not None
        assert user["id"] == created["id"]
        assert user["display_name"] == "John Doe"

    def test_get_nonexistent_user(self, store):
        """Should return None for nonexistent user."""
        user = store.get_scim_user("nonexistent")
        assert user is None

    def test_get_user_by_username(self, store):
        """Should get user by userName."""
        store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe"
        )

        user = store.get_scim_user_by_user_name("tenant-1", "jdoe")

        assert user is not None
        assert user["user_name"] == "jdoe"

    def test_get_user_by_external_id(self, store):
        """Should get user by externalId."""
        store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            external_id="ext-123"
        )

        user = store.get_scim_user_by_external_id("tenant-1", "ext-123")

        assert user is not None
        assert user["external_id"] == "ext-123"


class TestScimUserList:
    """Tests for listing SCIM users."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_list_empty(self, store):
        """Should return empty list when no users."""
        users = store.list_scim_users("tenant-1")
        assert users == []

    def test_list_users(self, store):
        """Should list all users for tenant."""
        store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        store.create_scim_user(tenant_id="tenant-1", user_name="user2")
        store.create_scim_user(tenant_id="tenant-2", user_name="user3")

        users = store.list_scim_users("tenant-1")

        assert len(users) == 2
        usernames = [u["user_name"] for u in users]
        assert "user1" in usernames
        assert "user2" in usernames
        assert "user3" not in usernames

    def test_list_with_pagination(self, store):
        """Should paginate results."""
        for i in range(5):
            store.create_scim_user(tenant_id="tenant-1", user_name=f"user{i}")

        page1 = store.list_scim_users("tenant-1", offset=0, limit=2)
        page2 = store.list_scim_users("tenant-1", offset=2, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2

    def test_count_users(self, store):
        """Should count users for tenant."""
        store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        store.create_scim_user(tenant_id="tenant-1", user_name="user2")
        store.create_scim_user(tenant_id="tenant-2", user_name="user3")

        count = store.count_scim_users("tenant-1")

        assert count == 2


class TestScimUserFind:
    """Tests for finding SCIM users by field."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_find_by_username(self, store):
        """Should find users by userName."""
        store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")
        store.create_scim_user(tenant_id="tenant-1", user_name="jsmith")

        users = store.find_scim_users("tenant-1", "user_name", "jdoe")

        assert len(users) == 1
        assert users[0]["user_name"] == "jdoe"

    def test_find_by_external_id(self, store):
        """Should find users by externalId."""
        store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            external_id="ext-123"
        )

        users = store.find_scim_users("tenant-1", "external_id", "ext-123")

        assert len(users) == 1
        assert users[0]["external_id"] == "ext-123"

    def test_find_by_email(self, store):
        """Should find users by email."""
        store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            email="jdoe@example.com"
        )

        users = store.find_scim_users("tenant-1", "email", "jdoe@example.com")

        assert len(users) == 1
        assert users[0]["email"] == "jdoe@example.com"

    def test_find_no_match(self, store):
        """Should return empty list when no match."""
        store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")

        users = store.find_scim_users("tenant-1", "user_name", "nomatch")

        assert users == []

    def test_find_invalid_field(self, store):
        """Should return empty list for invalid field."""
        users = store.find_scim_users("tenant-1", "invalid_field", "value")
        assert users == []


class TestScimUserUpdate:
    """Tests for updating SCIM users."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_update_display_name(self, store):
        """Should update displayName."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            display_name="John Doe"
        )

        store.update_scim_user(user["id"], {"display_name": "Jane Doe"})

        updated = store.get_scim_user(user["id"])
        assert updated["display_name"] == "Jane Doe"

    def test_update_active_false(self, store):
        """Should update active to false."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            active=True
        )

        store.update_scim_user(user["id"], {"active": False})

        updated = store.get_scim_user(user["id"])
        assert updated["active"] is False

    def test_update_multiple_fields(self, store):
        """Should update multiple fields at once."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe"
        )

        store.update_scim_user(user["id"], {
            "display_name": "John Doe",
            "given_name": "John",
            "family_name": "Doe",
            "email": "jdoe@example.com"
        })

        updated = store.get_scim_user(user["id"])
        assert updated["display_name"] == "John Doe"
        assert updated["given_name"] == "John"
        assert updated["family_name"] == "Doe"
        assert updated["email"] == "jdoe@example.com"

    def test_update_nonexistent_returns_false(self, store):
        """Should return False for nonexistent user."""
        result = store.update_scim_user("nonexistent", {"display_name": "Test"})
        assert result is False

    def test_update_empty_dict(self, store):
        """Should return True for empty updates."""
        user = store.create_scim_user(tenant_id="tenant-1", user_name="jdoe")
        result = store.update_scim_user(user["id"], {})
        assert result is True


class TestScimUserDelete:
    """Tests for deleting SCIM users."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_delete_user(self, store):
        """Should delete user."""
        user = store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe"
        )

        result = store.delete_scim_user(user["id"])

        assert result is True
        assert store.get_scim_user(user["id"]) is None

    def test_delete_nonexistent_returns_false(self, store):
        """Should return False for nonexistent user."""
        result = store.delete_scim_user("nonexistent")
        assert result is False


class TestTenantIsolation:
    """Tests for tenant isolation in user operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_list_isolated_by_tenant(self, store):
        """Should list only users from specified tenant."""
        store.create_scim_user(tenant_id="tenant-1", user_name="t1user")
        store.create_scim_user(tenant_id="tenant-2", user_name="t2user")

        t1_users = store.list_scim_users("tenant-1")
        t2_users = store.list_scim_users("tenant-2")

        assert len(t1_users) == 1
        assert t1_users[0]["user_name"] == "t1user"
        assert len(t2_users) == 1
        assert t2_users[0]["user_name"] == "t2user"

    def test_find_isolated_by_tenant(self, store):
        """Should find only users from specified tenant."""
        store.create_scim_user(
            tenant_id="tenant-1",
            user_name="jdoe",
            email="jdoe@t1.com"
        )
        store.create_scim_user(
            tenant_id="tenant-2",
            user_name="jdoe",
            email="jdoe@t2.com"
        )

        t1_users = store.find_scim_users("tenant-1", "user_name", "jdoe")
        t2_users = store.find_scim_users("tenant-2", "user_name", "jdoe")

        assert len(t1_users) == 1
        assert t1_users[0]["email"] == "jdoe@t1.com"
        assert len(t2_users) == 1
        assert t2_users[0]["email"] == "jdoe@t2.com"

    def test_count_isolated_by_tenant(self, store):
        """Should count only users from specified tenant."""
        store.create_scim_user(tenant_id="tenant-1", user_name="user1")
        store.create_scim_user(tenant_id="tenant-1", user_name="user2")
        store.create_scim_user(tenant_id="tenant-2", user_name="user3")

        assert store.count_scim_users("tenant-1") == 2
        assert store.count_scim_users("tenant-2") == 1


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
