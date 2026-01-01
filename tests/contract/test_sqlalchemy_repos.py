"""
Contract tests for SQLAlchemy repositories (v3.3.0 PR3).

Tests repository operations work correctly with the database backend.
"""

import pytest
import os
import sys

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestDBSession:
    """Tests for db_session.py."""

    def test_get_engine_import(self):
        """get_engine should be importable."""
        from db_session import get_engine
        assert callable(get_engine)

    def test_get_session_factory_import(self):
        """get_session_factory should be importable."""
        from db_session import get_session_factory
        assert callable(get_session_factory)

    def test_get_db_import(self):
        """get_db should be importable."""
        from db_session import get_db
        assert callable(get_db)

    def test_get_db_session_import(self):
        """get_db_session should be importable."""
        from db_session import get_db_session
        assert callable(get_db_session)


class TestDBModelsIntegration:
    """Integration tests for database models."""

    def test_base_metadata_tables(self):
        """Base.metadata should contain all expected tables."""
        from db_models import Base

        table_names = set(Base.metadata.tables.keys())
        expected = {"tenants", "users", "api_keys", "invites", "shares", "audit_log"}

        assert expected.issubset(table_names)

    def test_tenant_columns(self):
        """Tenant model should have correct columns."""
        from db_models import Tenant

        columns = {c.name for c in Tenant.__table__.columns}
        assert "id" in columns
        assert "name" in columns
        assert "created_at" in columns

    def test_user_columns(self):
        """User model should have correct columns."""
        from db_models import User

        columns = {c.name for c in User.__table__.columns}
        assert "id" in columns
        assert "tenant_id" in columns
        assert "email" in columns
        assert "password_hash" in columns
        assert "role" in columns
        assert "created_at" in columns
        assert "disabled" in columns
        assert "failed_attempts" in columns  # v3.2.0
        assert "lockout_until" in columns  # v3.2.0

    def test_api_key_columns(self):
        """APIKey model should have correct columns."""
        from db_models import APIKey

        columns = {c.name for c in APIKey.__table__.columns}
        assert "id" in columns
        assert "tenant_id" in columns
        assert "label" in columns
        assert "key_hash" in columns
        assert "role" in columns
        assert "created_at" in columns
        assert "revoked_at" in columns
        assert "last_used_at" in columns  # v3.2.0
        assert "rotated_from" in columns  # v3.2.0

    def test_invite_columns(self):
        """Invite model should have correct columns."""
        from db_models import Invite

        columns = {c.name for c in Invite.__table__.columns}
        assert "id" in columns
        assert "tenant_id" in columns
        assert "email" in columns
        assert "role" in columns
        assert "token_hash" in columns
        assert "created_at" in columns
        assert "expires_at" in columns
        assert "accepted_at" in columns
        assert "revoked_at" in columns
        assert "created_by" in columns

    def test_share_columns(self):
        """Share model should have correct columns."""
        from db_models import Share

        columns = {c.name for c in Share.__table__.columns}
        assert "id" in columns
        assert "tenant_id" in columns
        assert "resource_type" in columns
        assert "resource_id" in columns
        assert "token_hash" in columns
        assert "created_at" in columns
        assert "expires_at" in columns
        assert "revoked_at" in columns
        assert "created_by" in columns
        assert "label" in columns

    def test_audit_log_columns(self):
        """AuditLog model should have correct columns."""
        from db_models import AuditLog

        columns = {c.name for c in AuditLog.__table__.columns}
        assert "id" in columns
        assert "tenant_id" in columns
        assert "created_at" in columns
        assert "action" in columns
        assert "actor_id" in columns
        assert "actor_email" in columns
        assert "actor_role" in columns
        assert "auth_method" in columns
        assert "resource_type" in columns
        assert "resource_id" in columns
        assert "details_json" in columns
        assert "ip_address" in columns
        assert "user_agent" in columns
        assert "prev_hash" in columns  # v3.2.0
        assert "entry_hash" in columns  # v3.2.0


class TestAuthRepoInterface:
    """Tests for AuthRepo interface."""

    def test_auth_repo_tenant_methods(self):
        """AuthRepo should have all tenant methods."""
        from auth_repo import AuthRepo
        repo = AuthRepo()

        assert hasattr(repo, 'get_tenant')
        assert hasattr(repo, 'create_tenant')
        assert hasattr(repo, 'ensure_default_tenant')

    def test_auth_repo_user_methods(self):
        """AuthRepo should have all user methods."""
        from auth_repo import AuthRepo
        repo = AuthRepo()

        assert hasattr(repo, 'get_user_by_email')
        assert hasattr(repo, 'get_user_by_id')
        assert hasattr(repo, 'create_user')
        assert hasattr(repo, 'authenticate_user')
        assert hasattr(repo, 'list_users')
        assert hasattr(repo, 'count_active_admins')
        assert hasattr(repo, 'update_user')
        assert hasattr(repo, 'set_user_password')
        assert hasattr(repo, 'email_exists_in_tenant')

    def test_auth_repo_api_key_methods(self):
        """AuthRepo should have all API key methods."""
        from auth_repo import AuthRepo
        repo = AuthRepo()

        assert hasattr(repo, 'get_api_key_by_hash')
        assert hasattr(repo, 'create_api_key')
        assert hasattr(repo, 'list_api_keys')
        assert hasattr(repo, 'revoke_api_key')
        assert hasattr(repo, 'authenticate_api_key')
        assert hasattr(repo, 'update_api_key_last_used')

    def test_auth_repo_invite_methods(self):
        """AuthRepo should have all invite methods."""
        from auth_repo import AuthRepo
        repo = AuthRepo()

        assert hasattr(repo, 'create_invite')
        assert hasattr(repo, 'list_invites')
        assert hasattr(repo, 'get_invite_by_id')
        assert hasattr(repo, 'get_invite_by_token')
        assert hasattr(repo, 'revoke_invite')
        assert hasattr(repo, 'accept_invite')
        assert hasattr(repo, 'is_invite_expired')
        assert hasattr(repo, 'pending_invite_exists')

    def test_auth_repo_share_methods(self):
        """AuthRepo should have all share methods."""
        from auth_repo import AuthRepo
        repo = AuthRepo()

        assert hasattr(repo, 'create_share')
        assert hasattr(repo, 'list_shares')
        assert hasattr(repo, 'get_share_by_id')
        assert hasattr(repo, 'get_share_by_token')
        assert hasattr(repo, 'revoke_share')
        assert hasattr(repo, 'is_share_expired')
        assert hasattr(repo, 'validate_share_token')


class TestAuditRepoInterface:
    """Tests for AuditRepo interface."""

    def test_audit_repo_methods(self):
        """AuditRepo should have all required methods."""
        from audit_repo import AuditRepo
        repo = AuditRepo()

        assert hasattr(repo, 'log')
        assert hasattr(repo, 'query')
        assert hasattr(repo, 'export_csv')
        assert hasattr(repo, 'export_json')
        assert hasattr(repo, 'prune')
        assert hasattr(repo, 'verify_chain_integrity')

    def test_log_audit_function(self):
        """log_audit function should be available."""
        from audit_repo import log_audit
        assert callable(log_audit)

    def test_get_audit_repo_function(self):
        """get_audit_repo function should be available."""
        from audit_repo import get_audit_repo
        assert callable(get_audit_repo)
