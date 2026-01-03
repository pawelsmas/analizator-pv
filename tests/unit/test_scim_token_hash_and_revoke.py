"""
Unit tests for SCIM token hashing and revocation (v4.4.0 PR1).

Tests token creation, hashing, rotation, and revocation functionality.
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


class TestTokenHashing:
    """Tests for token hashing function."""

    def test_hash_token_returns_string(self):
        """hash_scim_token should return a string."""
        result = hash_scim_token("test-token")
        assert isinstance(result, str)

    def test_hash_token_deterministic(self):
        """Same token should produce same hash."""
        token = "my-secret-token"
        hash1 = hash_scim_token(token)
        hash2 = hash_scim_token(token)
        assert hash1 == hash2

    def test_hash_token_different_tokens_different_hashes(self):
        """Different tokens should produce different hashes."""
        hash1 = hash_scim_token("token-a")
        hash2 = hash_scim_token("token-b")
        assert hash1 != hash2

    def test_hash_token_length(self):
        """SHA256 hash should be 64 characters hex."""
        result = hash_scim_token("any-token")
        assert len(result) == 64

    def test_hash_token_hex_format(self):
        """Hash should be valid hex string."""
        result = hash_scim_token("test")
        int(result, 16)  # Should not raise

    def test_hash_token_includes_pepper(self):
        """Hash should include pepper (different from plain SHA256)."""
        import hashlib
        token = "test-token"
        plain_sha256 = hashlib.sha256(token.encode()).hexdigest()
        peppered_hash = hash_scim_token(token)
        assert plain_sha256 != peppered_hash


class TestScimStoreTokens:
    """Tests for ScimStore token operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_create_scim_token_returns_token_and_record(self, store):
        """create_scim_token should return plaintext token and record dict."""
        plaintext, record = store.create_scim_token(
            tenant_id="tenant-1",
            name="Test Token"
        )
        assert plaintext is not None
        assert isinstance(plaintext, str)
        assert plaintext.startswith("scim_")
        assert record is not None
        assert "id" in record
        assert record["tenant_id"] == "tenant-1"
        assert record["name"] == "Test Token"

    def test_create_scim_token_stores_hash_not_plaintext(self, store):
        """Token should be stored as hash, not plaintext."""
        plaintext, record = store.create_scim_token(
            tenant_id="tenant-1",
            name="Test Token"
        )

        # Verify hash via get_scim_token_by_hash
        expected_hash = hash_scim_token(plaintext)
        found = store.get_scim_token_by_hash(expected_hash)

        assert found is not None
        assert found["id"] == record["id"]

    def test_create_scim_token_unique_tokens(self, store):
        """Each token should have unique ID and plaintext."""
        token1, record1 = store.create_scim_token("tenant-1", "Token 1")
        token2, record2 = store.create_scim_token("tenant-1", "Token 2")

        assert record1["id"] != record2["id"]
        assert token1 != token2

    def test_get_scim_token_by_hash_valid(self, store):
        """get_scim_token_by_hash should return token for valid hash."""
        plaintext, record = store.create_scim_token("tenant-1", "Test")
        token_hash = hash_scim_token(plaintext)

        found = store.get_scim_token_by_hash(token_hash)

        assert found is not None
        assert found["id"] == record["id"]
        assert found["tenant_id"] == "tenant-1"

    def test_get_scim_token_by_hash_invalid(self, store):
        """get_scim_token_by_hash should return None for invalid hash."""
        result = store.get_scim_token_by_hash("invalid-hash")
        assert result is None

    def test_get_scim_token_by_hash_wrong_hash(self, store):
        """get_scim_token_by_hash should return None for wrong hash."""
        store.create_scim_token("tenant-1", "Test")
        result = store.get_scim_token_by_hash(hash_scim_token("different-token"))
        assert result is None

    def test_revoke_scim_token(self, store):
        """revoke_scim_token should mark token as revoked."""
        plaintext, record = store.create_scim_token("tenant-1", "Test")
        token_id = record["id"]

        result = store.revoke_scim_token(token_id)
        assert result is True

        # Token should no longer be found by hash
        token_hash = hash_scim_token(plaintext)
        found = store.get_scim_token_by_hash(token_hash)
        assert found is None

    def test_revoke_scim_token_nonexistent(self, store):
        """revoke_scim_token should return False for nonexistent token."""
        result = store.revoke_scim_token("nonexistent-id")
        assert result is False

    def test_revoked_token_hash_not_found(self, store):
        """Revoked token should not be found by hash."""
        plaintext, record = store.create_scim_token("tenant-1", "Test")
        store.revoke_scim_token(record["id"])

        token_hash = hash_scim_token(plaintext)
        result = store.get_scim_token_by_hash(token_hash)
        assert result is None

    def test_rotate_scim_token(self, store):
        """rotate_scim_token should delete old and create new token."""
        old_plaintext, old_record = store.create_scim_token("tenant-1", "Test")
        old_id = old_record["id"]

        result = store.rotate_scim_token(old_id)
        assert result is not None

        new_plaintext, new_record = result
        assert new_record["id"] != old_id
        assert new_plaintext != old_plaintext
        assert new_record["name"] == old_record["name"]
        assert new_record["tenant_id"] == old_record["tenant_id"]

        # Old token should not be found by hash (deleted)
        old_hash = hash_scim_token(old_plaintext)
        assert store.get_scim_token_by_hash(old_hash) is None

        # New token should be found by hash
        new_hash = hash_scim_token(new_plaintext)
        assert store.get_scim_token_by_hash(new_hash) is not None

    def test_rotate_scim_token_nonexistent(self, store):
        """rotate_scim_token should return None for nonexistent token."""
        result = store.rotate_scim_token("nonexistent")
        assert result is None

    def test_list_scim_tokens(self, store):
        """list_scim_tokens should return all tokens for tenant."""
        store.create_scim_token("tenant-1", "Token A")
        store.create_scim_token("tenant-1", "Token B")
        store.create_scim_token("tenant-2", "Token C")

        tokens = store.list_scim_tokens("tenant-1")

        assert len(tokens) == 2
        names = [t["name"] for t in tokens]
        assert "Token A" in names
        assert "Token B" in names

    def test_list_scim_tokens_includes_revoked(self, store):
        """list_scim_tokens includes revoked tokens."""
        _, record1 = store.create_scim_token("tenant-1", "Active")
        _, record2 = store.create_scim_token("tenant-1", "Revoked")
        store.revoke_scim_token(record2["id"])

        tokens = store.list_scim_tokens("tenant-1")

        # Both should be in list (revoked_at is exposed)
        assert len(tokens) == 2

    def test_list_scim_tokens_does_not_expose_hash(self, store):
        """list_scim_tokens should not expose token hash."""
        store.create_scim_token("tenant-1", "Test")

        tokens = store.list_scim_tokens("tenant-1")

        assert len(tokens) == 1
        assert "token_hash" not in tokens[0]

    def test_list_scim_tokens_empty(self, store):
        """list_scim_tokens should return empty list when no tokens."""
        tokens = store.list_scim_tokens("tenant-1")
        assert tokens == []

    def test_tenant_isolation_tokens(self, store):
        """Tokens should be isolated by tenant."""
        token1, record1 = store.create_scim_token("tenant-1", "T1")
        token2, record2 = store.create_scim_token("tenant-2", "T2")

        # Token1 hash should find tenant-1 token
        hash1 = hash_scim_token(token1)
        found1 = store.get_scim_token_by_hash(hash1)
        assert found1["tenant_id"] == "tenant-1"

        # Token2 hash should find tenant-2 token
        hash2 = hash_scim_token(token2)
        found2 = store.get_scim_token_by_hash(hash2)
        assert found2["tenant_id"] == "tenant-2"

        # List should be isolated
        assert len(store.list_scim_tokens("tenant-1")) == 1
        assert len(store.list_scim_tokens("tenant-2")) == 1

    def test_update_token_last_used(self, store):
        """update_scim_token_last_used should set last_used_at."""
        _, record = store.create_scim_token("tenant-1", "Test")
        token_id = record["id"]

        # Initially None
        token = store.get_scim_token(token_id)
        assert token["last_used_at"] is None

        # Update last used
        store.update_scim_token_last_used(token_id)

        token = store.get_scim_token(token_id)
        assert token["last_used_at"] is not None


class TestTokenEdgeCases:
    """Edge case tests for token operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_revoke_already_revoked_token(self, store):
        """Revoking already revoked token should return False."""
        _, record = store.create_scim_token("tenant-1", "Test")
        token_id = record["id"]

        # First revoke
        assert store.revoke_scim_token(token_id) is True

        # Second revoke
        assert store.revoke_scim_token(token_id) is False

    def test_rotate_revoked_token(self, store):
        """Rotating revoked token should fail."""
        _, record = store.create_scim_token("tenant-1", "Test")
        token_id = record["id"]
        store.revoke_scim_token(token_id)

        result = store.rotate_scim_token(token_id)
        assert result is None


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
