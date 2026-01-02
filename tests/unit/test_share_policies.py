"""
Unit tests for Share Policies enforcement (v3.7.0 PR3).

Tests share policies enforcement when project_id is provided:
- allow_public_shares enforcement
- share_max_expiry_hours enforcement
- Audit events for share operations
"""

import os
import sys
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Add bess-dispatch to path
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))

# Setup temp databases before imports
AUTH_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
AUDIT_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
os.environ["AUTH_DB_PATH"] = AUTH_DB
os.environ["AUDIT_STORE_PATH"] = AUDIT_DB
os.environ["AUDIT_STORE_ENABLED"] = "true"
os.environ["AUTH_ENABLED"] = "false"

from auth_store import AuthStore, ProjectRole
from auth_config import Role
from audit_store import AuditStore


@pytest.fixture
def temp_auth_db():
    """Create a temporary auth database."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def temp_audit_db():
    """Create a temporary audit database."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def auth_store(temp_auth_db):
    """Create an AuthStore with temp database."""
    return AuthStore(temp_auth_db)


@pytest.fixture
def audit_store(temp_audit_db):
    """Create an AuditStore with temp database."""
    return AuditStore(temp_audit_db)


@pytest.fixture
def tenant_and_user(auth_store):
    """Create tenant with admin user."""
    tenant = auth_store.create_tenant("test-tenant", "Test Tenant")
    admin = auth_store.create_user(
        tenant_id=tenant["id"],
        email="admin@example.com",
        password="password",
        role=Role.ADMIN,
    )
    return tenant, admin


class TestSharePoliciesEnforcement:
    """Tests for project share policy enforcement."""

    def test_create_share_without_project(self, auth_store, tenant_and_user):
        """Creating share without project_id works normally."""
        tenant, admin = tenant_and_user

        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            label="Test share",
            expires_hours=24,
        )

        assert share["id"] is not None
        assert share["resource_type"] == "run"
        assert share["resource_id"] == "run-123"
        assert share["project_id"] is None
        assert share["token"] is not None
        assert share["expires_at"] is not None

    def test_create_share_with_project_allows_public(self, auth_store, tenant_and_user):
        """Creating share with project that allows public shares works."""
        tenant, admin = tenant_and_user

        # Create project that allows public shares
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Public Project",
            created_by_user_id=admin["id"],
            allow_public_shares=True,
        )

        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            project_id=project["id"],
        )

        assert share["id"] is not None
        assert share["project_id"] == project["id"]
        assert share["token"] is not None

    def test_create_share_with_project_disallows_public(self, auth_store, tenant_and_user):
        """Creating share with project that disallows public shares raises error."""
        tenant, admin = tenant_and_user

        # Create project that disallows public shares
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Private Project",
            created_by_user_id=admin["id"],
            allow_public_shares=False,
        )

        with pytest.raises(ValueError) as exc_info:
            auth_store.create_share(
                tenant_id=tenant["id"],
                resource_type="run",
                resource_id="run-123",
                created_by=admin["id"],
                project_id=project["id"],
            )

        assert "PUBLIC_SHARES_DISABLED" in str(exc_info.value)

    def test_share_max_expiry_caps_requested_hours(self, auth_store, tenant_and_user):
        """Project max expiry caps the requested expires_hours."""
        tenant, admin = tenant_and_user

        # Create project with max 24 hour expiry
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Short Expiry Project",
            created_by_user_id=admin["id"],
            allow_public_shares=True,
            share_max_expiry_hours=24,
        )

        # Request 72 hours, should be capped to 24
        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            expires_hours=72,
            project_id=project["id"],
        )

        assert share["expires_at"] is not None
        # Parse expires_at and check it's ~24 hours from now, not 72
        expires_at = datetime.fromisoformat(share["expires_at"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(share["created_at"].replace("Z", "+00:00"))
        diff_hours = (expires_at - created_at).total_seconds() / 3600
        assert 23.9 < diff_hours < 24.1  # Allow small tolerance

    def test_share_max_expiry_sets_default_when_not_provided(self, auth_store, tenant_and_user):
        """Project max expiry sets expiry when none requested."""
        tenant, admin = tenant_and_user

        # Create project with max 48 hour expiry
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Default Expiry Project",
            created_by_user_id=admin["id"],
            allow_public_shares=True,
            share_max_expiry_hours=48,
        )

        # Don't specify expires_hours
        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            project_id=project["id"],
        )

        assert share["expires_at"] is not None
        # Should be set to 48 hours
        expires_at = datetime.fromisoformat(share["expires_at"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(share["created_at"].replace("Z", "+00:00"))
        diff_hours = (expires_at - created_at).total_seconds() / 3600
        assert 47.9 < diff_hours < 48.1

    def test_share_without_max_expiry_allows_no_expiry(self, auth_store, tenant_and_user):
        """Project without max expiry allows shares without expiry."""
        tenant, admin = tenant_and_user

        # Create project without max expiry
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="No Limit Project",
            created_by_user_id=admin["id"],
            allow_public_shares=True,
            share_max_expiry_hours=None,
        )

        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            project_id=project["id"],
            # No expires_hours
        )

        assert share["expires_at"] is None

    def test_share_respects_requested_expiry_when_under_max(self, auth_store, tenant_and_user):
        """Requested expiry is used when under project max."""
        tenant, admin = tenant_and_user

        # Create project with max 72 hour expiry
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Long Expiry Project",
            created_by_user_id=admin["id"],
            allow_public_shares=True,
            share_max_expiry_hours=72,
        )

        # Request 24 hours, should be honored (under max)
        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            expires_hours=24,
            project_id=project["id"],
        )

        expires_at = datetime.fromisoformat(share["expires_at"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(share["created_at"].replace("Z", "+00:00"))
        diff_hours = (expires_at - created_at).total_seconds() / 3600
        assert 23.9 < diff_hours < 24.1


class TestShareWithProjectId:
    """Tests for share operations with project_id."""

    def test_list_shares_includes_project_id(self, auth_store, tenant_and_user):
        """List shares returns project_id."""
        tenant, admin = tenant_and_user

        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Test Project",
            allow_public_shares=True,
        )

        auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            project_id=project["id"],
        )

        shares = auth_store.list_shares(tenant["id"])
        assert len(shares) == 1
        assert shares[0]["project_id"] == project["id"]

    def test_list_shares_filter_by_project_id(self, auth_store, tenant_and_user):
        """List shares can filter by project_id."""
        tenant, admin = tenant_and_user

        project1 = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Project 1",
            allow_public_shares=True,
        )
        project2 = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Project 2",
            allow_public_shares=True,
        )

        auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-1",
            created_by=admin["id"],
            project_id=project1["id"],
        )
        auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-2",
            created_by=admin["id"],
            project_id=project2["id"],
        )
        auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-3",
            created_by=admin["id"],
            # No project
        )

        # Filter by project1
        shares = auth_store.list_shares(tenant["id"], project_id=project1["id"])
        assert len(shares) == 1
        assert shares[0]["resource_id"] == "run-1"

        # Filter by project2
        shares = auth_store.list_shares(tenant["id"], project_id=project2["id"])
        assert len(shares) == 1
        assert shares[0]["resource_id"] == "run-2"

        # No filter - all shares
        shares = auth_store.list_shares(tenant["id"])
        assert len(shares) == 3

    def test_get_share_by_id_includes_project_id(self, auth_store, tenant_and_user):
        """Get share by ID returns project_id."""
        tenant, admin = tenant_and_user

        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Test Project",
            allow_public_shares=True,
        )

        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            project_id=project["id"],
        )

        retrieved = auth_store.get_share_by_id(share["id"], tenant["id"])
        assert retrieved is not None
        assert retrieved["project_id"] == project["id"]

    def test_get_share_by_token_includes_project_id(self, auth_store, tenant_and_user):
        """Get share by token returns project_id."""
        tenant, admin = tenant_and_user

        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Test Project",
            allow_public_shares=True,
        )

        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            project_id=project["id"],
        )

        retrieved = auth_store.get_share_by_token(share["token"])
        assert retrieved is not None
        assert retrieved["project_id"] == project["id"]


class TestShareAuditEvents:
    """Tests for audit logging of share operations."""

    def test_audit_log_records_share_created(self, temp_auth_db, temp_audit_db):
        """Audit store can record share_created events."""
        audit_store = AuditStore(temp_audit_db)

        entry_id = audit_store.log(
            tenant_id="test-tenant",
            action="share_created",
            actor_id="user-123",
            actor_email="admin@example.com",
            actor_role="admin",
            auth_method="jwt",
            resource_type="share",
            resource_id="share-456",
            details={
                "shared_resource_type": "run",
                "shared_resource_id": "run-789",
                "project_id": "project-123",
                "expires_at": "2026-01-03T12:00:00Z",
            },
        )

        assert entry_id is not None

        # Query and verify
        result = audit_store.query(tenant_id="test-tenant", action="share_created")
        assert result["total"] == 1
        assert result["items"][0]["action"] == "share_created"
        assert result["items"][0]["resource_id"] == "share-456"
        assert result["items"][0]["details"]["project_id"] == "project-123"

    def test_audit_log_records_share_revoked(self, temp_audit_db):
        """Audit store can record share_revoked events."""
        audit_store = AuditStore(temp_audit_db)

        entry_id = audit_store.log(
            tenant_id="test-tenant",
            action="share_revoked",
            actor_id="user-123",
            actor_email="admin@example.com",
            resource_type="share",
            resource_id="share-456",
            details={
                "shared_resource_type": "run",
                "shared_resource_id": "run-789",
                "project_id": "project-123",
            },
        )

        assert entry_id is not None

        result = audit_store.query(tenant_id="test-tenant", action="share_revoked")
        assert result["total"] == 1

    def test_audit_log_records_share_create_denied(self, temp_audit_db):
        """Audit store can record share_create_denied events."""
        audit_store = AuditStore(temp_audit_db)

        entry_id = audit_store.log(
            tenant_id="test-tenant",
            action="share_create_denied",
            actor_id="user-123",
            actor_email="admin@example.com",
            resource_type="run",
            resource_id="run-789",
            details={
                "reason": "public_shares_disabled",
                "project_id": "project-123",
            },
        )

        assert entry_id is not None

        result = audit_store.query(tenant_id="test-tenant", action="share_create_denied")
        assert result["total"] == 1
        assert result["items"][0]["details"]["reason"] == "public_shares_disabled"


class TestSharePoliciesEdgeCases:
    """Edge case tests for share policies."""

    def test_nonexistent_project_id_ignores_policies(self, auth_store, tenant_and_user):
        """Share with nonexistent project_id ignores policy checks."""
        tenant, admin = tenant_and_user

        # Create share with nonexistent project_id
        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            project_id="nonexistent-project",
        )

        # Should succeed (no project found means no policies to enforce)
        assert share["id"] is not None
        assert share["project_id"] == "nonexistent-project"

    def test_archived_project_still_enforces_policies(self, auth_store, tenant_and_user):
        """Archived project still enforces share policies."""
        tenant, admin = tenant_and_user

        # Create and archive project that disallows public shares
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Archived Project",
            allow_public_shares=False,
        )
        auth_store.archive_project(project["id"], tenant["id"])

        # Attempt to create share should still be denied
        with pytest.raises(ValueError) as exc_info:
            auth_store.create_share(
                tenant_id=tenant["id"],
                resource_type="run",
                resource_id="run-123",
                created_by=admin["id"],
                project_id=project["id"],
            )

        assert "PUBLIC_SHARES_DISABLED" in str(exc_info.value)

    def test_zero_max_expiry_allows_any_expiry(self, auth_store, tenant_and_user):
        """share_max_expiry_hours=0 (or None) means no limit."""
        tenant, admin = tenant_and_user

        # Create project with explicit 0 max expiry
        project = auth_store.create_project(
            tenant_id=tenant["id"],
            name="Zero Max Project",
            allow_public_shares=True,
            share_max_expiry_hours=0,  # Should be treated as None
        )

        # Update to set share_max_expiry_hours to None (0 should become None)
        project = auth_store.update_project(
            project_id=project["id"],
            tenant_id=tenant["id"],
            share_max_expiry_hours=0,  # This should set to None
        )

        # Request very long expiry
        share = auth_store.create_share(
            tenant_id=tenant["id"],
            resource_type="run",
            resource_id="run-123",
            created_by=admin["id"],
            expires_hours=8760,  # 1 year
            project_id=project["id"],
        )

        expires_at = datetime.fromisoformat(share["expires_at"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(share["created_at"].replace("Z", "+00:00"))
        diff_hours = (expires_at - created_at).total_seconds() / 3600
        assert 8759 < diff_hours < 8761


class TestShareMigration:
    """Tests for share project_id migration."""

    def test_shares_table_has_project_id_column(self, auth_store, tenant_and_user):
        """Shares table should have project_id column after migration."""
        # The migration runs during AuthStore init
        conn = sqlite3.connect(auth_store.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(shares)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "project_id" in columns
        finally:
            conn.close()

    def test_shares_project_id_index_exists(self, auth_store, tenant_and_user):
        """Index on shares.project_id should exist."""
        conn = sqlite3.connect(auth_store.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_shares_project'")
            result = cursor.fetchone()
            assert result is not None
        finally:
            conn.close()
