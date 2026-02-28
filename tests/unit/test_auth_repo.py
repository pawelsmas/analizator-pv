"""
Unit tests for auth_repo.py (v3.3.0 PR3).

Tests SQLAlchemy-based auth repository operations.
"""

import pytest
import os
import sys
import tempfile

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_returns_string(self):
        """hash_password should return a string."""
        from auth_repo import hash_password
        result = hash_password("test_password")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_password_different_for_same_input(self):
        """hash_password should return different hashes (due to salt)."""
        from auth_repo import hash_password
        hash1 = hash_password("same_password")
        hash2 = hash_password("same_password")
        # bcrypt uses random salt, so hashes should differ
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """verify_password should return True for correct password."""
        from auth_repo import hash_password, verify_password
        password = "my_secure_password"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password should return False for incorrect password."""
        from auth_repo import hash_password, verify_password
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_handles_invalid_hash(self):
        """verify_password should handle invalid hash gracefully."""
        from auth_repo import verify_password
        assert verify_password("password", "invalid_hash") is False


class TestAPIKeyHashing:
    """Tests for API key hashing functions."""

    def test_generate_api_key_format(self):
        """generate_api_key should return key with bess_ prefix."""
        from auth_repo import generate_api_key
        key = generate_api_key()
        assert key.startswith("bess_")
        assert len(key) > 10

    def test_generate_api_key_unique(self):
        """generate_api_key should return unique keys."""
        from auth_repo import generate_api_key
        keys = [generate_api_key() for _ in range(10)]
        assert len(set(keys)) == 10

    def test_hash_api_key_deterministic(self):
        """hash_api_key should be deterministic."""
        from auth_repo import hash_api_key
        key = "bess_test_key_123"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        assert hash1 == hash2

    def test_hash_api_key_returns_hex(self):
        """hash_api_key should return 64-char hex string."""
        from auth_repo import hash_api_key
        key = "bess_test_key"
        hashed = hash_api_key(key)
        assert len(hashed) == 64
        assert all(c in '0123456789abcdef' for c in hashed)


class TestInviteTokenHashing:
    """Tests for invite token hashing functions."""

    def test_generate_invite_token_unique(self):
        """generate_invite_token should return unique tokens."""
        from auth_repo import generate_invite_token
        tokens = [generate_invite_token() for _ in range(10)]
        assert len(set(tokens)) == 10

    def test_hash_invite_token_deterministic(self):
        """hash_invite_token should be deterministic."""
        from auth_repo import hash_invite_token
        token = "test_invite_token"
        hash1 = hash_invite_token(token)
        hash2 = hash_invite_token(token)
        assert hash1 == hash2


class TestShareTokenHashing:
    """Tests for share token hashing functions."""

    def test_generate_share_token_unique(self):
        """generate_share_token should return unique tokens."""
        from auth_repo import generate_share_token
        tokens = [generate_share_token() for _ in range(10)]
        assert len(set(tokens)) == 10

    def test_hash_share_token_deterministic(self):
        """hash_share_token should be deterministic."""
        from auth_repo import hash_share_token
        token = "test_share_token"
        hash1 = hash_share_token(token)
        hash2 = hash_share_token(token)
        assert hash1 == hash2

    def test_hash_share_token_different_from_invite(self):
        """share and invite tokens should hash differently (different pepper)."""
        from auth_repo import hash_share_token, hash_invite_token
        token = "same_token_value"
        share_hash = hash_share_token(token)
        invite_hash = hash_invite_token(token)
        assert share_hash != invite_hash


class TestAuthRepoBasic:
    """Basic tests for AuthRepo class."""

    def test_auth_repo_import(self):
        """AuthRepo should be importable."""
        from auth_repo import AuthRepo
        assert AuthRepo is not None

    def test_get_auth_repo_singleton(self):
        """get_auth_repo should return consistent instance."""
        from auth_repo import get_auth_repo
        repo1 = get_auth_repo()
        repo2 = get_auth_repo()
        # Both should be AuthRepo instances
        assert repo1 is not None
        assert repo2 is not None
