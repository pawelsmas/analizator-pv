"""
Unit tests for share retention functions (v3.8.0 PR5).

Tests:
- purge_expired_shares
- purge_revoked_shares
- get_retention_stats
"""

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from auth_store import AuthStore, hash_share_token


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


@pytest.fixture
def auth_store(temp_db):
    """Create an AuthStore instance with temp database."""
    return AuthStore(db_path=temp_db)


@pytest.fixture
def tenant_and_user(auth_store):
    """Create a test tenant and user."""
    tenant_id = f"test_tenant_{uuid.uuid4().hex[:8]}"
    auth_store.create_tenant(tenant_id, "Test Tenant")
    user = auth_store.create_user(tenant_id, f"user_{uuid.uuid4().hex[:6]}@test.com", "password123")
    return tenant_id, user["id"]


def create_share_with_date(auth_store, tenant_id, user_id, expires_at=None, revoked_at=None, resource_id=None):
    """Helper to create a share with specific dates directly in DB."""
    import sqlite3
    from auth_store import generate_share_token, hash_share_token

    share_id = str(uuid.uuid4())
    token = generate_share_token()
    token_hash = hash_share_token(token)
    created_at = datetime.now(timezone.utc).isoformat()
    resource_id = resource_id or f"run_{uuid.uuid4().hex[:8]}"

    conn = sqlite3.connect(auth_store.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO shares (id, tenant_id, resource_type, resource_id, token_hash, created_at, expires_at, revoked_at, created_by, label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            share_id,
            tenant_id,
            "run",
            resource_id,
            token_hash,
            created_at,
            expires_at.isoformat() if expires_at else None,
            revoked_at.isoformat() if revoked_at else None,
            user_id,
            "Test share",
        ))
        conn.commit()
    finally:
        conn.close()

    return share_id, token


def create_access_log_with_date(auth_store, share_id, tenant_id, accessed_at):
    """Helper to create an access log with specific date."""
    import sqlite3

    log_id = str(uuid.uuid4())

    conn = sqlite3.connect(auth_store.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO share_access_logs (id, share_id, tenant_id, accessed_at, ip_address, user_agent, access_result)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id,
            share_id,
            tenant_id,
            accessed_at.isoformat(),
            "192.168.1.1",
            "TestAgent/1.0",
            "success",
        ))
        conn.commit()
    finally:
        conn.close()

    return log_id


class TestPurgeExpiredShares:
    """Tests for purge_expired_shares."""

    def test_purge_expired_shares_deletes_old_expired(self, auth_store, tenant_and_user):
        """Test that expired shares older than threshold are deleted."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create share expired 40 days ago (should be deleted with default 30 days)
        expires_40_days_ago = now - timedelta(days=40)
        share_id_1, _ = create_share_with_date(auth_store, tenant_id, user_id, expires_at=expires_40_days_ago)

        # Create share expired 10 days ago (should NOT be deleted with default 30 days)
        expires_10_days_ago = now - timedelta(days=10)
        share_id_2, _ = create_share_with_date(auth_store, tenant_id, user_id, expires_at=expires_10_days_ago)

        # Purge
        deleted = auth_store.purge_expired_shares(tenant_id, expired_before_days=30)

        # Verify
        assert deleted == 1

        # Share 1 should be gone
        share_1 = auth_store.get_share_by_id(share_id_1, tenant_id)
        assert share_1 is None

        # Share 2 should still exist
        share_2 = auth_store.get_share_by_id(share_id_2, tenant_id)
        assert share_2 is not None

    def test_purge_expired_shares_does_not_affect_active(self, auth_store, tenant_and_user):
        """Test that active (non-expired) shares are not deleted."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create share expiring in 10 days (active)
        expires_in_future = now + timedelta(days=10)
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id, expires_at=expires_in_future)

        # Purge
        deleted = auth_store.purge_expired_shares(tenant_id, expired_before_days=30)

        # Verify
        assert deleted == 0
        share = auth_store.get_share_by_id(share_id, tenant_id)
        assert share is not None

    def test_purge_expired_shares_does_not_affect_no_expiry(self, auth_store, tenant_and_user):
        """Test that shares with no expiry are not deleted."""
        tenant_id, user_id = tenant_and_user

        # Create share with no expiry
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id, expires_at=None)

        # Purge
        deleted = auth_store.purge_expired_shares(tenant_id, expired_before_days=30)

        # Verify
        assert deleted == 0
        share = auth_store.get_share_by_id(share_id, tenant_id)
        assert share is not None

    def test_purge_expired_shares_also_deletes_access_logs(self, auth_store, tenant_and_user):
        """Test that access logs for purged shares are also deleted."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create expired share
        expires_40_days_ago = now - timedelta(days=40)
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id, expires_at=expires_40_days_ago)

        # Create access logs for this share
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=35))
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=36))

        # Verify logs exist
        assert auth_store.count_share_access_logs(share_id, tenant_id) == 2

        # Purge
        deleted = auth_store.purge_expired_shares(tenant_id, expired_before_days=30)

        # Verify share and logs deleted
        assert deleted == 1
        assert auth_store.count_share_access_logs(share_id, tenant_id) == 0

    def test_purge_expired_shares_custom_threshold(self, auth_store, tenant_and_user):
        """Test custom threshold for purging."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create share expired 5 days ago
        expires_5_days_ago = now - timedelta(days=5)
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id, expires_at=expires_5_days_ago)

        # Purge with 3 day threshold (should delete)
        deleted = auth_store.purge_expired_shares(tenant_id, expired_before_days=3)

        # Verify
        assert deleted == 1

    def test_purge_expired_shares_empty_result(self, auth_store, tenant_and_user):
        """Test purging when no shares to purge."""
        tenant_id, _ = tenant_and_user

        # Purge empty
        deleted = auth_store.purge_expired_shares(tenant_id, expired_before_days=30)

        # Verify
        assert deleted == 0


class TestPurgeRevokedShares:
    """Tests for purge_revoked_shares."""

    def test_purge_revoked_shares_deletes_old_revoked(self, auth_store, tenant_and_user):
        """Test that revoked shares older than threshold are deleted."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create share revoked 40 days ago (should be deleted)
        revoked_40_days_ago = now - timedelta(days=40)
        share_id_1, _ = create_share_with_date(auth_store, tenant_id, user_id, revoked_at=revoked_40_days_ago)

        # Create share revoked 10 days ago (should NOT be deleted)
        revoked_10_days_ago = now - timedelta(days=10)
        share_id_2, _ = create_share_with_date(auth_store, tenant_id, user_id, revoked_at=revoked_10_days_ago)

        # Purge
        deleted = auth_store.purge_revoked_shares(tenant_id, revoked_before_days=30)

        # Verify
        assert deleted == 1

        # Share 1 should be gone
        share_1 = auth_store.get_share_by_id(share_id_1, tenant_id)
        assert share_1 is None

        # Share 2 should still exist (but revoked)
        share_2 = auth_store.get_share_by_id(share_id_2, tenant_id)
        assert share_2 is not None

    def test_purge_revoked_shares_does_not_affect_active(self, auth_store, tenant_and_user):
        """Test that active (non-revoked) shares are not deleted."""
        tenant_id, user_id = tenant_and_user

        # Create active share
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id, revoked_at=None)

        # Purge
        deleted = auth_store.purge_revoked_shares(tenant_id, revoked_before_days=30)

        # Verify
        assert deleted == 0
        share = auth_store.get_share_by_id(share_id, tenant_id)
        assert share is not None

    def test_purge_revoked_shares_also_deletes_access_logs(self, auth_store, tenant_and_user):
        """Test that access logs for purged shares are also deleted."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create revoked share
        revoked_40_days_ago = now - timedelta(days=40)
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id, revoked_at=revoked_40_days_ago)

        # Create access logs
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=45))

        # Verify log exists
        assert auth_store.count_share_access_logs(share_id, tenant_id) == 1

        # Purge
        deleted = auth_store.purge_revoked_shares(tenant_id, revoked_before_days=30)

        # Verify
        assert deleted == 1
        assert auth_store.count_share_access_logs(share_id, tenant_id) == 0


class TestGetRetentionStats:
    """Tests for get_retention_stats."""

    def test_get_retention_stats_empty(self, auth_store, tenant_and_user):
        """Test retention stats with no shares."""
        tenant_id, _ = tenant_and_user

        stats = auth_store.get_retention_stats(tenant_id)

        assert stats["active_shares"] == 0
        assert stats["expired_shares"] == 0
        assert stats["expired_shares_purgeable"] == 0
        assert stats["revoked_shares"] == 0
        assert stats["revoked_shares_purgeable"] == 0
        assert stats["total_access_logs"] == 0
        assert stats["access_logs_purgeable"] == 0

    def test_get_retention_stats_with_shares(self, auth_store, tenant_and_user):
        """Test retention stats with various share states."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create active share
        create_share_with_date(auth_store, tenant_id, user_id, expires_at=now + timedelta(days=10))

        # Create expired share (recently - not purgeable)
        create_share_with_date(auth_store, tenant_id, user_id, expires_at=now - timedelta(days=5))

        # Create expired share (old - purgeable)
        create_share_with_date(auth_store, tenant_id, user_id, expires_at=now - timedelta(days=40))

        # Create revoked share (recently - not purgeable)
        create_share_with_date(auth_store, tenant_id, user_id, revoked_at=now - timedelta(days=5))

        # Create revoked share (old - purgeable)
        create_share_with_date(auth_store, tenant_id, user_id, revoked_at=now - timedelta(days=40))

        stats = auth_store.get_retention_stats(tenant_id)

        assert stats["active_shares"] == 1
        assert stats["expired_shares"] == 2
        assert stats["expired_shares_purgeable"] == 1
        assert stats["revoked_shares"] == 2
        assert stats["revoked_shares_purgeable"] == 1

    def test_get_retention_stats_with_access_logs(self, auth_store, tenant_and_user):
        """Test retention stats with access logs."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create share
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id)

        # Create recent access log
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=5))

        # Create old access log (purgeable at 90 days)
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=100))

        stats = auth_store.get_retention_stats(tenant_id)

        assert stats["total_access_logs"] == 2
        assert stats["access_logs_purgeable"] == 1

    def test_get_retention_stats_tenant_isolation(self, auth_store):
        """Test that retention stats are isolated by tenant."""
        now = datetime.now(timezone.utc)

        # Create two tenants
        tenant1_id = f"tenant1_{uuid.uuid4().hex[:8]}"
        tenant2_id = f"tenant2_{uuid.uuid4().hex[:8]}"
        auth_store.create_tenant(tenant1_id, "Tenant 1")
        auth_store.create_tenant(tenant2_id, "Tenant 2")

        user1 = auth_store.create_user(tenant1_id, f"user1@test.com", "password")
        user2 = auth_store.create_user(tenant2_id, f"user2@test.com", "password")

        # Create shares in tenant1
        create_share_with_date(auth_store, tenant1_id, user1["id"])
        create_share_with_date(auth_store, tenant1_id, user1["id"])
        create_share_with_date(auth_store, tenant1_id, user1["id"])

        # Create shares in tenant2
        create_share_with_date(auth_store, tenant2_id, user2["id"])

        # Verify isolation
        stats1 = auth_store.get_retention_stats(tenant1_id)
        stats2 = auth_store.get_retention_stats(tenant2_id)

        assert stats1["active_shares"] == 3
        assert stats2["active_shares"] == 1


class TestPruneAccessLogs:
    """Additional tests for prune_share_access_logs."""

    def test_prune_access_logs_preserves_recent(self, auth_store, tenant_and_user):
        """Test that recent access logs are preserved."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create share
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id)

        # Create recent log
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=5))

        # Prune with 90 day threshold
        deleted = auth_store.prune_share_access_logs(tenant_id, older_than_days=90)

        # Verify not deleted
        assert deleted == 0
        assert auth_store.count_share_access_logs(share_id, tenant_id) == 1

    def test_prune_access_logs_deletes_old(self, auth_store, tenant_and_user):
        """Test that old access logs are deleted."""
        tenant_id, user_id = tenant_and_user
        now = datetime.now(timezone.utc)

        # Create share
        share_id, _ = create_share_with_date(auth_store, tenant_id, user_id)

        # Create old logs
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=100))
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=110))

        # Create recent log
        create_access_log_with_date(auth_store, share_id, tenant_id, now - timedelta(days=5))

        # Prune
        deleted = auth_store.prune_share_access_logs(tenant_id, older_than_days=90)

        # Verify
        assert deleted == 2
        assert auth_store.count_share_access_logs(share_id, tenant_id) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
