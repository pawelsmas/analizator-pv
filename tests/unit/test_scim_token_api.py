"""
Unit tests for SCIM token management API (v4.4.0 PR2).

Tests the token API business logic (not Flask routes).
"""

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from scim_store import ScimStore, hash_scim_token


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


class TestTokenListOperation:
    """Tests for listing tokens."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_list_returns_empty_when_no_tokens(self, store):
        """Should return empty list when no tokens exist."""
        tokens = store.list_scim_tokens("tenant-1")
        assert tokens == []

    def test_list_returns_tenant_tokens_only(self, store):
        """Should return only tokens for the specified tenant."""
        store.create_scim_token("tenant-1", "Token A")
        store.create_scim_token("tenant-1", "Token B")
        store.create_scim_token("tenant-2", "Other Token")

        tokens = store.list_scim_tokens("tenant-1")

        assert len(tokens) == 2
        names = [t["name"] for t in tokens]
        assert "Token A" in names
        assert "Token B" in names
        assert "Other Token" not in names

    def test_list_does_not_expose_hash(self, store):
        """Token list should not include token_hash."""
        store.create_scim_token("tenant-1", "Token")

        tokens = store.list_scim_tokens("tenant-1")

        assert len(tokens) == 1
        assert "token_hash" not in tokens[0]

    def test_list_includes_metadata(self, store):
        """Token list should include id, name, created_at, etc."""
        store.create_scim_token("tenant-1", "Token")

        tokens = store.list_scim_tokens("tenant-1")

        assert len(tokens) == 1
        assert "id" in tokens[0]
        assert "name" in tokens[0]
        assert "created_at" in tokens[0]


class TestTokenCreateOperation:
    """Tests for creating tokens."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_create_returns_plaintext_and_record(self, store):
        """Should return plaintext token and record dict."""
        plaintext, record = store.create_scim_token("tenant-1", "My Token")

        assert plaintext is not None
        assert plaintext.startswith("scim_")
        assert "id" in record
        assert record["name"] == "My Token"
        assert record["tenant_id"] == "tenant-1"

    def test_create_token_stored_as_hash(self, store):
        """Token should be stored as hash, not plaintext."""
        plaintext, record = store.create_scim_token("tenant-1", "Token")

        # Should be able to find by hash
        found = store.get_scim_token_by_hash(hash_scim_token(plaintext))
        assert found is not None
        assert found["id"] == record["id"]

    def test_create_duplicate_name_fails(self, store):
        """Should raise error for duplicate name in same tenant."""
        store.create_scim_token("tenant-1", "Token")

        with pytest.raises(Exception) as exc_info:
            store.create_scim_token("tenant-1", "Token")

        assert "UNIQUE constraint" in str(exc_info.value)

    def test_create_same_name_different_tenants(self, store):
        """Same name should be allowed in different tenants."""
        _, record1 = store.create_scim_token("tenant-1", "Token")
        _, record2 = store.create_scim_token("tenant-2", "Token")

        assert record1["id"] != record2["id"]


class TestTokenGetOperation:
    """Tests for getting a single token."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_get_returns_token_metadata(self, store):
        """Should return token metadata."""
        _, record = store.create_scim_token("tenant-1", "My Token")

        token = store.get_scim_token(record["id"])

        assert token is not None
        assert token["id"] == record["id"]
        assert token["name"] == "My Token"

    def test_get_nonexistent_returns_none(self, store):
        """Should return None for nonexistent token."""
        token = store.get_scim_token("nonexistent-id")
        assert token is None

    def test_get_includes_revoked_at(self, store):
        """Should include revoked_at field."""
        _, record = store.create_scim_token("tenant-1", "Token")

        token = store.get_scim_token(record["id"])

        assert "revoked_at" in token
        assert token["revoked_at"] is None

    def test_get_after_revoke_shows_revoked_at(self, store):
        """Revoked token should have revoked_at set."""
        _, record = store.create_scim_token("tenant-1", "Token")
        store.revoke_scim_token(record["id"])

        token = store.get_scim_token(record["id"])

        assert token["revoked_at"] is not None


class TestTokenRevokeOperation:
    """Tests for revoking tokens."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_revoke_marks_token_invalid(self, store):
        """Revoked token should not be found by hash."""
        plaintext, record = store.create_scim_token("tenant-1", "Token")

        success = store.revoke_scim_token(record["id"])

        assert success is True
        assert store.get_scim_token_by_hash(hash_scim_token(plaintext)) is None

    def test_revoke_nonexistent_returns_false(self, store):
        """Should return False for nonexistent token."""
        result = store.revoke_scim_token("nonexistent")
        assert result is False

    def test_revoke_already_revoked_returns_false(self, store):
        """Should return False when token already revoked."""
        _, record = store.create_scim_token("tenant-1", "Token")
        store.revoke_scim_token(record["id"])

        result = store.revoke_scim_token(record["id"])
        assert result is False


class TestTokenRotateOperation:
    """Tests for rotating tokens."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_rotate_creates_new_token(self, store):
        """Should create new token and delete old."""
        old_plaintext, old_record = store.create_scim_token("tenant-1", "Token")

        result = store.rotate_scim_token(old_record["id"])

        assert result is not None
        new_plaintext, new_record = result
        assert new_plaintext != old_plaintext
        assert new_record["id"] != old_record["id"]
        assert new_record["name"] == "Token"

    def test_rotate_old_token_invalid(self, store):
        """Old token should not be valid after rotation."""
        old_plaintext, old_record = store.create_scim_token("tenant-1", "Token")

        store.rotate_scim_token(old_record["id"])

        # Old token should not be found
        assert store.get_scim_token_by_hash(hash_scim_token(old_plaintext)) is None

    def test_rotate_new_token_valid(self, store):
        """New token should be valid after rotation."""
        _, old_record = store.create_scim_token("tenant-1", "Token")

        result = store.rotate_scim_token(old_record["id"])
        new_plaintext, _ = result

        # New token should be found
        assert store.get_scim_token_by_hash(hash_scim_token(new_plaintext)) is not None

    def test_rotate_nonexistent_returns_none(self, store):
        """Should return None for nonexistent token."""
        result = store.rotate_scim_token("nonexistent")
        assert result is None

    def test_rotate_revoked_returns_none(self, store):
        """Should return None for revoked token."""
        _, record = store.create_scim_token("tenant-1", "Token")
        store.revoke_scim_token(record["id"])

        result = store.rotate_scim_token(record["id"])
        assert result is None


class TestTokenTenantIsolation:
    """Tests for tenant isolation in token operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_list_isolated_by_tenant(self, store):
        """List should only return tokens for the tenant."""
        store.create_scim_token("tenant-1", "T1 Token")
        store.create_scim_token("tenant-2", "T2 Token")

        t1_tokens = store.list_scim_tokens("tenant-1")
        t2_tokens = store.list_scim_tokens("tenant-2")

        assert len(t1_tokens) == 1
        assert len(t2_tokens) == 1
        assert t1_tokens[0]["name"] == "T1 Token"
        assert t2_tokens[0]["name"] == "T2 Token"

    def test_token_hash_returns_correct_tenant(self, store):
        """Token hash lookup should return correct tenant."""
        token1, _ = store.create_scim_token("tenant-1", "Token")
        token2, _ = store.create_scim_token("tenant-2", "Token")

        record1 = store.get_scim_token_by_hash(hash_scim_token(token1))
        record2 = store.get_scim_token_by_hash(hash_scim_token(token2))

        assert record1["tenant_id"] == "tenant-1"
        assert record2["tenant_id"] == "tenant-2"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
