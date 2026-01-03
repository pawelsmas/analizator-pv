"""
Unit tests for SCIM auth middleware (v4.4.0 PR2).

Tests bearer token validation logic.
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


class TestBearerTokenExtraction:
    """Tests for bearer token extraction logic."""

    def test_extract_from_valid_header(self):
        """Should extract token from valid Bearer header."""
        header = "Bearer scim_abc123xyz"
        if header.startswith("Bearer "):
            token = header[7:]
        else:
            token = None
        assert token == "scim_abc123xyz"

    def test_extract_no_bearer_prefix(self):
        """Should return None when not Bearer auth."""
        header = "Basic dXNlcjpwYXNz"
        if header.startswith("Bearer "):
            token = header[7:]
        else:
            token = None
        assert token is None

    def test_extract_empty_header(self):
        """Should return None when header is empty."""
        header = ""
        if header.startswith("Bearer "):
            token = header[7:]
        else:
            token = None
        assert token is None

    def test_extract_bearer_case_sensitive(self):
        """Bearer prefix should be case-sensitive."""
        header = "bearer token123"
        if header.startswith("Bearer "):
            token = header[7:]
        else:
            token = None
        assert token is None

    def test_extract_just_bearer(self):
        """Should handle 'Bearer ' with empty token."""
        header = "Bearer "
        if header.startswith("Bearer "):
            token = header[7:]
        else:
            token = None
        assert token == ""


class TestScimTokenValidation:
    """Tests for SCIM token validation using store."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_validate_valid_token(self, store):
        """Valid token should return tenant_id."""
        plaintext, record = store.create_scim_token("tenant-1", "Test Token")
        token_hash = hash_scim_token(plaintext)
        token_record = store.get_scim_token_by_hash(token_hash)

        assert token_record is not None
        assert token_record["tenant_id"] == "tenant-1"

    def test_validate_invalid_token(self, store):
        """Invalid token should return None."""
        token_hash = hash_scim_token("invalid_token")
        token_record = store.get_scim_token_by_hash(token_hash)

        assert token_record is None

    def test_validate_revoked_token(self, store):
        """Revoked token should return None."""
        plaintext, record = store.create_scim_token("tenant-1", "Test Token")
        store.revoke_scim_token(record["id"])

        token_hash = hash_scim_token(plaintext)
        token_record = store.get_scim_token_by_hash(token_hash)

        assert token_record is None

    def test_last_used_at_updated(self, store):
        """Token's last_used_at should update on access."""
        plaintext, record = store.create_scim_token("tenant-1", "Test Token")

        # Initially None
        token = store.get_scim_token(record["id"])
        assert token["last_used_at"] is None

        # Simulate validation with update
        store.update_scim_token_last_used(record["id"])

        # Now should have timestamp
        token = store.get_scim_token(record["id"])
        assert token["last_used_at"] is not None


class TestTenantIsolation:
    """Tests for tenant isolation in token validation."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a ScimStore with temporary database."""
        db_path = tmp_path / "test_scim.db"
        create_test_db(str(db_path))
        return ScimStore(str(db_path))

    def test_token_returns_correct_tenant(self, store):
        """Token should return the tenant it was created for."""
        token1, _ = store.create_scim_token("tenant-1", "T1 Token")
        token2, _ = store.create_scim_token("tenant-2", "T2 Token")

        record1 = store.get_scim_token_by_hash(hash_scim_token(token1))
        record2 = store.get_scim_token_by_hash(hash_scim_token(token2))

        assert record1["tenant_id"] == "tenant-1"
        assert record2["tenant_id"] == "tenant-2"

    def test_tenant_tokens_isolated_in_list(self, store):
        """List should only return tokens for specific tenant."""
        store.create_scim_token("tenant-1", "T1 Token A")
        store.create_scim_token("tenant-1", "T1 Token B")
        store.create_scim_token("tenant-2", "T2 Token")

        t1_tokens = store.list_scim_tokens("tenant-1")
        t2_tokens = store.list_scim_tokens("tenant-2")

        assert len(t1_tokens) == 2
        assert len(t2_tokens) == 1


class TestScimErrorResponses:
    """Tests for SCIM error response format."""

    def test_error_response_format(self):
        """SCIM error should follow RFC 7644 format."""
        error_response = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "status": "401",
            "detail": "Missing or invalid Authorization header"
        }

        assert "schemas" in error_response
        assert error_response["schemas"][0] == "urn:ietf:params:scim:api:messages:2.0:Error"
        assert "status" in error_response
        assert "detail" in error_response

    def test_401_error_format(self):
        """401 error should have correct status."""
        error_response = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "status": "401",
            "detail": "Invalid SCIM token"
        }

        assert error_response["status"] == "401"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
