"""
Unit tests for Deprovision Helper (v4.4.0 PR8).

Tests for user deprovisioning semantics.
"""

import os
import pytest
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone


@pytest.fixture
def temp_db():
    """Create a temporary database with required tables."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    # Create users table
    cursor.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Create SCIM identities table
    cursor.execute("""
        CREATE TABLE scim_identities (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            scim_user_id TEXT UNIQUE NOT NULL,
            user_id TEXT REFERENCES users(id),
            external_id TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # Create user_sessions table
    cursor.execute("""
        CREATE TABLE user_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            token_hash TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            revoked_reason TEXT
        )
    """)

    # Create api_keys table
    cursor.execute("""
        CREATE TABLE api_keys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            key_hash TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            revoked_reason TEXT
        )
    """)

    # Create project_memberships table
    cursor.execute("""
        CREATE TABLE project_memberships (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            scim_group_id TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

    yield path

    os.unlink(path)


@pytest.fixture
def helper(temp_db):
    """Create DeprovisionHelper with temp database."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

    # Mock auth_config
    sys.modules['auth_config'] = type('Module', (), {'AUTH_DB_PATH': temp_db})()

    from deprovision_helper import DeprovisionHelper, reset_deprovision_helper
    reset_deprovision_helper()
    return DeprovisionHelper(temp_db)


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return str(uuid.uuid4())


def create_user(db_path: str, user_id: str, email: str, active: int = 1) -> None:
    """Create a test user."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO users (id, email, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, email, active, now, now)
    )
    conn.commit()
    conn.close()


def create_scim_identity(db_path: str, tenant_id: str, scim_user_id: str, user_id: str) -> None:
    """Create a SCIM identity linking to portal user."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO scim_identities (id, tenant_id, scim_user_id, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), tenant_id, scim_user_id, user_id, now)
    )
    conn.commit()
    conn.close()


def create_session(db_path: str, user_id: str) -> str:
    """Create a test session."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO user_sessions (id, user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_id, str(uuid.uuid4()), now, now)
    )
    conn.commit()
    conn.close()
    return session_id


def create_api_key(db_path: str, user_id: str, name: str = "test-key") -> str:
    """Create a test API key."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    key_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at) VALUES (?, ?, ?, ?, ?)",
        (key_id, user_id, str(uuid.uuid4()), name, now)
    )
    conn.commit()
    conn.close()
    return key_id


def create_membership(db_path: str, tenant_id: str, user_id: str, project_id: str, source: str = "manual") -> str:
    """Create a test project membership."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    membership_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO project_memberships (id, tenant_id, project_id, user_id, role, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (membership_id, tenant_id, project_id, user_id, "editor", source, now)
    )
    conn.commit()
    conn.close()
    return membership_id


class TestDeprovisionUser:
    """Tests for deprovision_user method."""

    def test_deprovision_revokes_sessions(self, helper, temp_db, tenant_id):
        """Test that deprovisioning revokes all active sessions."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com")
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)
        create_session(temp_db, user_id)
        create_session(temp_db, user_id)
        create_session(temp_db, user_id)

        result = helper.deprovision_user(scim_user_id)

        assert result["sessions_revoked"] == 3

    def test_deprovision_revokes_api_keys(self, helper, temp_db, tenant_id):
        """Test that deprovisioning revokes all API keys."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com")
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)
        create_api_key(temp_db, user_id, "key1")
        create_api_key(temp_db, user_id, "key2")

        result = helper.deprovision_user(scim_user_id)

        assert result["api_keys_revoked"] == 2

    def test_deprovision_revokes_scim_memberships(self, helper, temp_db, tenant_id):
        """Test that deprovisioning revokes SCIM-managed memberships."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com")
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)
        create_membership(temp_db, tenant_id, user_id, str(uuid.uuid4()), source="scim")
        create_membership(temp_db, tenant_id, user_id, str(uuid.uuid4()), source="scim")

        result = helper.deprovision_user(scim_user_id)

        assert result["scim_memberships_revoked"] == 2

    def test_deprovision_preserves_manual_memberships(self, helper, temp_db, tenant_id):
        """Test that manual memberships are NOT revoked."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com")
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)
        create_membership(temp_db, tenant_id, user_id, str(uuid.uuid4()), source="manual")

        result = helper.deprovision_user(scim_user_id)

        assert result["scim_memberships_revoked"] == 0

        # Verify manual membership still exists
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM project_memberships WHERE user_id = ?", (user_id,))
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_deprovision_marks_user_inactive(self, helper, temp_db, tenant_id):
        """Test that user is marked as inactive."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com")
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)

        helper.deprovision_user(scim_user_id)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT active FROM users WHERE id = ?", (user_id,))
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_deprovision_no_linked_user(self, helper, temp_db):
        """Test deprovisioning when no linked user exists."""
        scim_user_id = str(uuid.uuid4())

        result = helper.deprovision_user(scim_user_id)

        assert result["sessions_revoked"] == 0
        assert result["api_keys_revoked"] == 0
        assert result["scim_memberships_revoked"] == 0

    def test_deprovision_hard_delete(self, helper, temp_db, tenant_id):
        """Test hard delete removes SCIM identity."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com")
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)

        result = helper.deprovision_user(scim_user_id, hard_delete=True)

        assert result["hard_deleted"] is True

        # Verify SCIM identity is deleted
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM scim_identities WHERE scim_user_id = ?", (scim_user_id,))
        assert cursor.fetchone()[0] == 0
        conn.close()


class TestReprovisionUser:
    """Tests for reprovision_user method."""

    def test_reprovision_reactivates_user(self, helper, temp_db, tenant_id):
        """Test that reprovisioning reactivates the user."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com", active=0)
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)

        result = helper.reprovision_user(scim_user_id)

        assert result["reactivated"] is True

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT active FROM users WHERE id = ?", (user_id,))
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_reprovision_already_active(self, helper, temp_db, tenant_id):
        """Test reprovisioning an already active user."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com", active=1)
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)

        result = helper.reprovision_user(scim_user_id)

        assert result["reactivated"] is False

    def test_reprovision_no_linked_user(self, helper, temp_db):
        """Test reprovisioning when no linked user exists."""
        scim_user_id = str(uuid.uuid4())

        result = helper.reprovision_user(scim_user_id)

        assert result["reactivated"] is False


class TestGetUserResources:
    """Tests for get_user_resources method."""

    def test_get_resources_counts(self, helper, temp_db, tenant_id):
        """Test getting resource counts for a user."""
        user_id = str(uuid.uuid4())
        scim_user_id = str(uuid.uuid4())

        create_user(temp_db, user_id, "test@example.com")
        create_scim_identity(temp_db, tenant_id, scim_user_id, user_id)
        create_session(temp_db, user_id)
        create_session(temp_db, user_id)
        create_api_key(temp_db, user_id, "key1")
        create_membership(temp_db, tenant_id, user_id, str(uuid.uuid4()), source="scim")
        create_membership(temp_db, tenant_id, user_id, str(uuid.uuid4()), source="manual")

        result = helper.get_user_resources(scim_user_id)

        assert result["portal_user_id"] == user_id
        assert result["active_sessions"] == 2
        assert result["active_api_keys"] == 1
        assert result["scim_memberships"] == 1
        assert result["manual_memberships"] == 1

    def test_get_resources_no_linked_user(self, helper, temp_db):
        """Test getting resources when no linked user exists."""
        scim_user_id = str(uuid.uuid4())

        result = helper.get_user_resources(scim_user_id)

        assert result["portal_user_id"] is None
        assert result["active_sessions"] == 0


class TestRevokeAllSessions:
    """Tests for revoke_all_sessions method."""

    def test_revoke_sessions(self, helper, temp_db):
        """Test revoking all sessions for a user."""
        user_id = str(uuid.uuid4())
        create_user(temp_db, user_id, "test@example.com")
        create_session(temp_db, user_id)
        create_session(temp_db, user_id)

        count = helper.revoke_all_sessions(user_id, reason="test_revoke")

        assert count == 2

        # Verify sessions are revoked
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT revoked_reason FROM user_sessions WHERE user_id = ?", (user_id,))
        for row in cursor.fetchall():
            assert row[0] == "test_revoke"
        conn.close()

    def test_revoke_sessions_already_revoked(self, helper, temp_db):
        """Test that already revoked sessions are not counted."""
        user_id = str(uuid.uuid4())
        create_user(temp_db, user_id, "test@example.com")
        create_session(temp_db, user_id)

        # Revoke once
        helper.revoke_all_sessions(user_id)

        # Try to revoke again
        count = helper.revoke_all_sessions(user_id)

        assert count == 0


class TestRevokeAllApiKeys:
    """Tests for revoke_all_api_keys method."""

    def test_revoke_api_keys(self, helper, temp_db):
        """Test revoking all API keys for a user."""
        user_id = str(uuid.uuid4())
        create_user(temp_db, user_id, "test@example.com")
        create_api_key(temp_db, user_id, "key1")
        create_api_key(temp_db, user_id, "key2")

        count = helper.revoke_all_api_keys(user_id, reason="test_revoke")

        assert count == 2

    def test_revoke_api_keys_already_revoked(self, helper, temp_db):
        """Test that already revoked API keys are not counted."""
        user_id = str(uuid.uuid4())
        create_user(temp_db, user_id, "test@example.com")
        create_api_key(temp_db, user_id, "key1")

        # Revoke once
        helper.revoke_all_api_keys(user_id)

        # Try to revoke again
        count = helper.revoke_all_api_keys(user_id)

        assert count == 0
