"""
Unit tests for audit_repo.py (v3.3.0 PR3).

Tests SQLAlchemy-based audit repository operations.
"""

import pytest
import os
import sys

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestComputeEntryHash:
    """Tests for compute_entry_hash function."""

    def test_compute_entry_hash_returns_hex(self):
        """compute_entry_hash should return 64-char hex string."""
        from audit_repo import compute_entry_hash

        entry = {
            "id": "test-id-123",
            "tenant_id": "tenant-1",
            "created_at": "2024-01-01T00:00:00+00:00",
            "action": "login_success",
            "actor_id": "user-1",
            "resource_type": None,
            "resource_id": None,
        }
        result = compute_entry_hash(entry)

        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in '0123456789abcdef' for c in result)

    def test_compute_entry_hash_deterministic(self):
        """compute_entry_hash should be deterministic."""
        from audit_repo import compute_entry_hash

        entry = {
            "id": "test-id-123",
            "tenant_id": "tenant-1",
            "created_at": "2024-01-01T00:00:00+00:00",
            "action": "login_success",
            "actor_id": "user-1",
            "resource_type": None,
            "resource_id": None,
        }
        hash1 = compute_entry_hash(entry)
        hash2 = compute_entry_hash(entry)

        assert hash1 == hash2

    def test_compute_entry_hash_different_for_different_entries(self):
        """compute_entry_hash should differ for different entries."""
        from audit_repo import compute_entry_hash

        entry1 = {
            "id": "test-id-1",
            "tenant_id": "tenant-1",
            "created_at": "2024-01-01T00:00:00+00:00",
            "action": "login_success",
            "actor_id": "user-1",
            "resource_type": None,
            "resource_id": None,
        }
        entry2 = {
            "id": "test-id-2",
            "tenant_id": "tenant-1",
            "created_at": "2024-01-01T00:00:00+00:00",
            "action": "login_success",
            "actor_id": "user-1",
            "resource_type": None,
            "resource_id": None,
        }

        assert compute_entry_hash(entry1) != compute_entry_hash(entry2)

    def test_compute_entry_hash_includes_prev_hash(self):
        """compute_entry_hash should include prev_hash in computation."""
        from audit_repo import compute_entry_hash

        entry = {
            "id": "test-id-1",
            "tenant_id": "tenant-1",
            "created_at": "2024-01-01T00:00:00+00:00",
            "action": "login_success",
            "actor_id": "user-1",
            "resource_type": None,
            "resource_id": None,
        }

        hash_without_prev = compute_entry_hash(entry, None)
        hash_with_prev = compute_entry_hash(entry, "abc123")

        assert hash_without_prev != hash_with_prev

    def test_compute_entry_hash_chain(self):
        """compute_entry_hash should support chain computation."""
        from audit_repo import compute_entry_hash

        entry1 = {
            "id": "entry-1",
            "tenant_id": "tenant-1",
            "created_at": "2024-01-01T00:00:00+00:00",
            "action": "action_1",
            "actor_id": None,
            "resource_type": None,
            "resource_id": None,
        }
        entry2 = {
            "id": "entry-2",
            "tenant_id": "tenant-1",
            "created_at": "2024-01-01T00:00:01+00:00",
            "action": "action_2",
            "actor_id": None,
            "resource_type": None,
            "resource_id": None,
        }

        hash1 = compute_entry_hash(entry1, None)
        hash2 = compute_entry_hash(entry2, hash1)

        # Both should be valid hashes
        assert len(hash1) == 64
        assert len(hash2) == 64
        # Chain should be reproducible
        assert compute_entry_hash(entry2, hash1) == hash2


class TestAuditRepoBasic:
    """Basic tests for AuditRepo class."""

    def test_audit_repo_import(self):
        """AuditRepo should be importable."""
        from audit_repo import AuditRepo
        assert AuditRepo is not None

    def test_get_audit_repo_singleton(self):
        """get_audit_repo should return consistent instance."""
        from audit_repo import get_audit_repo
        repo1 = get_audit_repo()
        repo2 = get_audit_repo()
        assert repo1 is not None
        assert repo2 is not None

    def test_audit_repo_has_log_method(self):
        """AuditRepo should have log method."""
        from audit_repo import AuditRepo
        repo = AuditRepo()
        assert hasattr(repo, 'log')
        assert callable(repo.log)

    def test_audit_repo_has_query_method(self):
        """AuditRepo should have query method."""
        from audit_repo import AuditRepo
        repo = AuditRepo()
        assert hasattr(repo, 'query')
        assert callable(repo.query)

    def test_audit_repo_has_export_methods(self):
        """AuditRepo should have export methods."""
        from audit_repo import AuditRepo
        repo = AuditRepo()
        assert hasattr(repo, 'export_csv')
        assert hasattr(repo, 'export_json')
        assert callable(repo.export_csv)
        assert callable(repo.export_json)

    def test_audit_repo_has_prune_method(self):
        """AuditRepo should have prune method."""
        from audit_repo import AuditRepo
        repo = AuditRepo()
        assert hasattr(repo, 'prune')
        assert callable(repo.prune)

    def test_audit_repo_has_verify_chain_method(self):
        """AuditRepo should have verify_chain_integrity method."""
        from audit_repo import AuditRepo
        repo = AuditRepo()
        assert hasattr(repo, 'verify_chain_integrity')
        assert callable(repo.verify_chain_integrity)


class TestLogAuditFunction:
    """Tests for log_audit helper function."""

    def test_log_audit_import(self):
        """log_audit function should be importable."""
        from audit_repo import log_audit
        assert callable(log_audit)

    def test_log_audit_respects_enabled_flag(self):
        """log_audit should respect AUDIT_STORE_ENABLED flag."""
        import audit_repo
        # Save original value
        original = audit_repo.AUDIT_STORE_ENABLED

        try:
            # Disable audit
            audit_repo.AUDIT_STORE_ENABLED = False
            result = audit_repo.log_audit("tenant-1", "test_action")
            assert result is None
        finally:
            # Restore original
            audit_repo.AUDIT_STORE_ENABLED = original


class TestDBModels:
    """Tests for db_models.py."""

    def test_models_import(self):
        """All models should be importable."""
        from db_models import Base, Tenant, User, APIKey, Invite, Share, AuditLog

        assert Base is not None
        assert Tenant is not None
        assert User is not None
        assert APIKey is not None
        assert Invite is not None
        assert Share is not None
        assert AuditLog is not None

    def test_tenant_tablename(self):
        """Tenant should have correct table name."""
        from db_models import Tenant
        assert Tenant.__tablename__ == "tenants"

    def test_user_tablename(self):
        """User should have correct table name."""
        from db_models import User
        assert User.__tablename__ == "users"

    def test_api_key_tablename(self):
        """APIKey should have correct table name."""
        from db_models import APIKey
        assert APIKey.__tablename__ == "api_keys"

    def test_invite_tablename(self):
        """Invite should have correct table name."""
        from db_models import Invite
        assert Invite.__tablename__ == "invites"

    def test_share_tablename(self):
        """Share should have correct table name."""
        from db_models import Share
        assert Share.__tablename__ == "shares"

    def test_audit_log_tablename(self):
        """AuditLog should have correct table name."""
        from db_models import AuditLog
        assert AuditLog.__tablename__ == "audit_log"

    def test_tenant_to_dict(self):
        """Tenant.to_dict should return dict with correct keys."""
        from db_models import Tenant
        from datetime import datetime, timezone

        tenant = Tenant(
            id="test-tenant",
            name="Test Tenant",
            created_at=datetime.now(timezone.utc),
        )
        result = tenant.to_dict()

        assert "id" in result
        assert "name" in result
        assert "created_at" in result
        assert result["id"] == "test-tenant"
        assert result["name"] == "Test Tenant"

    def test_user_to_dict_excludes_hash(self):
        """User.to_dict should exclude password_hash by default."""
        from db_models import User
        from datetime import datetime, timezone

        user = User(
            id="test-user",
            tenant_id="tenant-1",
            email="test@example.com",
            password_hash="secret_hash",
            role="admin",
            created_at=datetime.now(timezone.utc),
            disabled=False,
        )
        result = user.to_dict()

        assert "password_hash" not in result
        assert "email" in result
        assert result["email"] == "test@example.com"

    def test_user_to_dict_includes_hash_when_requested(self):
        """User.to_dict should include password_hash when requested."""
        from db_models import User
        from datetime import datetime, timezone

        user = User(
            id="test-user",
            tenant_id="tenant-1",
            email="test@example.com",
            password_hash="secret_hash",
            role="admin",
            created_at=datetime.now(timezone.utc),
            disabled=False,
        )
        result = user.to_dict(include_hash=True)

        assert "password_hash" in result
        assert result["password_hash"] == "secret_hash"
