"""
Unit tests for auth core (v3.0.0 PR1).

Tests verify:
- Password hashing and verification
- JWT token creation and decoding
- API key hashing (deterministic)
- AuthStore operations
- Role permission checks
"""

import pytest
import sys
import tempfile
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestPasswordHashing:
    """Tests for password hashing utilities."""

    def test_hash_password_returns_string(self):
        """hash_password should return a string."""
        from auth_store import hash_password

        result = hash_password("test_password")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_password_different_for_same_input(self):
        """Bcrypt should produce different hashes for same password (salted)."""
        from auth_store import hash_password

        hash1 = hash_password("same_password")
        hash2 = hash_password("same_password")
        assert hash1 != hash2  # Different due to random salt

    def test_verify_password_correct(self):
        """verify_password should return True for correct password."""
        from auth_store import hash_password, verify_password

        password = "my_secret_password"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password should return False for wrong password."""
        from auth_store import hash_password, verify_password

        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False


class TestApiKeyHashing:
    """Tests for API key hashing."""

    def test_hash_api_key_deterministic(self):
        """hash_api_key should be deterministic (same input = same output)."""
        from auth_store import hash_api_key

        key = "bess_test_key_12345"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        assert hash1 == hash2

    def test_hash_api_key_different_for_different_keys(self):
        """Different keys should produce different hashes."""
        from auth_store import hash_api_key

        hash1 = hash_api_key("key_one")
        hash2 = hash_api_key("key_two")
        assert hash1 != hash2

    def test_generate_api_key_format(self):
        """generate_api_key should return bess_ prefixed key."""
        from auth_store import generate_api_key

        key = generate_api_key()
        assert key.startswith("bess_")
        assert len(key) > 10


class TestJwtTokens:
    """Tests for JWT token operations."""

    def test_create_access_token_returns_string(self):
        """create_access_token should return a string."""
        # Set JWT_SECRET for testing
        import os
        os.environ["JWT_SECRET"] = "test_secret_key_for_unit_tests"

        # Reload module to pick up new secret
        import importlib
        import auth_config
        importlib.reload(auth_config)
        import auth_jwt
        importlib.reload(auth_jwt)

        from auth_jwt import create_access_token

        token = create_access_token({"sub": "user123", "tenant_id": "default"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_access_token_valid(self):
        """decode_access_token should decode valid token."""
        import os
        os.environ["JWT_SECRET"] = "test_secret_key_for_unit_tests"

        import importlib
        import auth_config
        importlib.reload(auth_config)
        import auth_jwt
        importlib.reload(auth_jwt)

        from auth_jwt import create_access_token, decode_access_token

        data = {"sub": "user456", "tenant_id": "tenant_a", "role": "admin"}
        token = create_access_token(data)

        decoded = decode_access_token(token)
        assert decoded is not None
        assert decoded["sub"] == "user456"
        assert decoded["tenant_id"] == "tenant_a"
        assert decoded["role"] == "admin"

    def test_decode_access_token_invalid(self):
        """decode_access_token should return None for invalid token."""
        import os
        os.environ["JWT_SECRET"] = "test_secret_key_for_unit_tests"

        import importlib
        import auth_config
        importlib.reload(auth_config)
        import auth_jwt
        importlib.reload(auth_jwt)

        from auth_jwt import decode_access_token

        result = decode_access_token("invalid.token.here")
        assert result is None


class TestRolePermissions:
    """Tests for role permission checks."""

    def test_admin_has_all_permissions(self):
        """Admin should have all permissions."""
        from auth_config import Role

        admin = Role.ADMIN
        assert admin.has_permission(Role.VIEWER) is True
        assert admin.has_permission(Role.EDITOR) is True
        assert admin.has_permission(Role.ADMIN) is True

    def test_editor_has_viewer_permission(self):
        """Editor should have viewer permission."""
        from auth_config import Role

        editor = Role.EDITOR
        assert editor.has_permission(Role.VIEWER) is True
        assert editor.has_permission(Role.EDITOR) is True
        assert editor.has_permission(Role.ADMIN) is False

    def test_viewer_limited_permissions(self):
        """Viewer should only have viewer permission."""
        from auth_config import Role

        viewer = Role.VIEWER
        assert viewer.has_permission(Role.VIEWER) is True
        assert viewer.has_permission(Role.EDITOR) is False
        assert viewer.has_permission(Role.ADMIN) is False

    def test_service_role_same_as_editor(self):
        """Service role should have same level as editor."""
        from auth_config import Role

        service = Role.SERVICE
        assert service.has_permission(Role.VIEWER) is True
        assert service.has_permission(Role.EDITOR) is True
        assert service.has_permission(Role.ADMIN) is False


class TestAuthStore:
    """Tests for AuthStore operations."""

    def test_create_and_get_tenant(self):
        """Should create and retrieve tenant."""
        from auth_store import AuthStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuthStore(db_path)
        tenant = store.create_tenant("test_tenant", "Test Tenant")

        assert tenant["id"] == "test_tenant"
        assert tenant["name"] == "Test Tenant"

        retrieved = store.get_tenant("test_tenant")
        assert retrieved is not None
        assert retrieved["name"] == "Test Tenant"

    def test_create_and_authenticate_user(self):
        """Should create user and authenticate with correct password."""
        from auth_store import AuthStore
        from auth_config import Role

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuthStore(db_path)
        store.create_tenant("tenant1", "Tenant One")
        store.create_user("tenant1", "test@example.com", "secure_password", Role.EDITOR)

        # Authenticate with correct password
        user = store.authenticate_user("test@example.com", "secure_password")
        assert user is not None
        assert user["email"] == "test@example.com"
        assert user["role"] == "editor"

        # Authenticate with wrong password
        user = store.authenticate_user("test@example.com", "wrong_password")
        assert user is None

    def test_create_and_authenticate_api_key(self):
        """Should create API key and authenticate."""
        from auth_store import AuthStore
        from auth_config import Role

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuthStore(db_path)
        store.create_tenant("tenant2", "Tenant Two")

        # Create API key
        key_info = store.create_api_key("tenant2", "Test Key", Role.SERVICE)
        assert "api_key" in key_info  # Plaintext shown once
        assert key_info["api_key"].startswith("bess_")

        # Authenticate with key
        auth_result = store.authenticate_api_key(key_info["api_key"])
        assert auth_result is not None
        assert auth_result["tenant_id"] == "tenant2"
        assert auth_result["role"] == "service"

    def test_revoke_api_key(self):
        """Should revoke API key and prevent authentication."""
        from auth_store import AuthStore
        from auth_config import Role

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuthStore(db_path)
        store.create_tenant("tenant3", "Tenant Three")

        key_info = store.create_api_key("tenant3", "Revokable Key", Role.SERVICE)
        plaintext = key_info["api_key"]

        # Key works before revoke
        assert store.authenticate_api_key(plaintext) is not None

        # Revoke
        revoked = store.revoke_api_key(key_info["id"], "tenant3")
        assert revoked is True

        # Key no longer works
        assert store.authenticate_api_key(plaintext) is None

    def test_list_api_keys_excludes_plaintext(self):
        """List API keys should not include plaintext."""
        from auth_store import AuthStore
        from auth_config import Role

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuthStore(db_path)
        store.create_tenant("tenant4", "Tenant Four")
        store.create_api_key("tenant4", "Key One", Role.SERVICE)
        store.create_api_key("tenant4", "Key Two", Role.EDITOR)

        keys = store.list_api_keys("tenant4")
        assert len(keys) == 2

        for key in keys:
            assert "api_key" not in key  # No plaintext
            assert "key_hash" not in key  # No hash exposed in list


class TestAuthContext:
    """Tests for AuthContext model."""

    def test_auth_context_creation(self):
        """Should create AuthContext with required fields."""
        from auth_config import AuthContext, Role

        ctx = AuthContext(
            tenant_id="test_tenant",
            user_id="user123",
            email="user@example.com",
            role=Role.EDITOR,
            auth_method="jwt",
        )

        assert ctx.tenant_id == "test_tenant"
        assert ctx.user_id == "user123"
        assert ctx.role == Role.EDITOR
        assert ctx.auth_method == "jwt"

    def test_auth_context_optional_fields(self):
        """AuthContext should allow optional fields."""
        from auth_config import AuthContext, Role

        ctx = AuthContext(
            tenant_id="default",
            role=Role.ADMIN,
            auth_method="disabled",
        )

        assert ctx.user_id is None
        assert ctx.email is None
