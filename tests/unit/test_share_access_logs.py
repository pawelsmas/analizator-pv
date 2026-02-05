"""
Unit tests for Share access logs (v3.8.0 PR3).

Tests for auth_store share access log functions:
- log_share_access
- list_share_access_logs
- get_share_stats
- count_share_access_logs
- prune_share_access_logs
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Add bess-dispatch to path
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def auth_store(temp_db):
    """Create AuthStore with temporary database."""
    from auth_store import AuthStore
    store = AuthStore(db_path=temp_db)
    store.create_tenant("test_tenant", "Test Tenant")
    from auth_config import Role
    store.create_user("test_tenant", "test@test.com", "password123", Role.ADMIN)
    return store


@pytest.fixture
def test_share(auth_store):
    """Create a test share."""
    return auth_store.create_share(
        tenant_id="test_tenant",
        resource_type="run",
        resource_id="run_123",
        created_by="user_123",
    )


class TestLogShareAccess:
    """Tests for log_share_access."""

    def test_logs_successful_access(self, auth_store, test_share):
        """log_share_access creates a log entry for successful access."""
        result = auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
        )

        assert result["id"] is not None
        assert result["share_id"] == test_share["id"]
        assert result["tenant_id"] == "test_tenant"
        assert result["access_result"] == "success"
        assert result["ip_address"] == "192.168.1.100"
        assert result["user_agent"] == "Mozilla/5.0"
        assert result["accessed_at"] is not None

    def test_logs_denied_access(self, auth_store, test_share):
        """log_share_access creates a log entry for denied access."""
        result = auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="denied_share_password_invalid",
            ip_address="10.0.0.1",
        )

        assert result["access_result"] == "denied_share_password_invalid"

    def test_logs_without_ip(self, auth_store, test_share):
        """log_share_access works without IP address."""
        result = auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
        )

        assert result["ip_address"] is None
        assert result["user_agent"] is None

    def test_logs_multiple_accesses(self, auth_store, test_share):
        """log_share_access creates multiple log entries."""
        for i in range(5):
            auth_store.log_share_access(
                share_id=test_share["id"],
                tenant_id="test_tenant",
                access_result="success",
                ip_address=f"192.168.1.{i}",
            )

        logs = auth_store.list_share_access_logs(test_share["id"], "test_tenant")
        assert len(logs) == 5


class TestListShareAccessLogs:
    """Tests for list_share_access_logs."""

    def test_returns_logs_in_order(self, auth_store, test_share):
        """list_share_access_logs returns logs in descending order (newest first)."""
        for i in range(3):
            auth_store.log_share_access(
                share_id=test_share["id"],
                tenant_id="test_tenant",
                access_result="success",
                ip_address=f"192.168.1.{i}",
            )

        logs = auth_store.list_share_access_logs(test_share["id"], "test_tenant")
        assert len(logs) == 3
        # Newest first - last IP should be first in results
        assert logs[0]["ip_address"] == "192.168.1.2"

    def test_respects_limit(self, auth_store, test_share):
        """list_share_access_logs respects limit parameter."""
        for i in range(10):
            auth_store.log_share_access(
                share_id=test_share["id"],
                tenant_id="test_tenant",
                access_result="success",
            )

        logs = auth_store.list_share_access_logs(test_share["id"], "test_tenant", limit=5)
        assert len(logs) == 5

    def test_respects_offset(self, auth_store, test_share):
        """list_share_access_logs respects offset parameter."""
        for i in range(10):
            auth_store.log_share_access(
                share_id=test_share["id"],
                tenant_id="test_tenant",
                access_result="success",
                ip_address=f"192.168.1.{i}",
            )

        logs = auth_store.list_share_access_logs(test_share["id"], "test_tenant", limit=5, offset=5)
        assert len(logs) == 5
        # Should skip first 5 (newest), so start from IP 4
        assert logs[0]["ip_address"] == "192.168.1.4"

    def test_returns_empty_for_no_logs(self, auth_store, test_share):
        """list_share_access_logs returns empty list when no logs exist."""
        logs = auth_store.list_share_access_logs(test_share["id"], "test_tenant")
        assert logs == []

    def test_filters_by_share_id(self, auth_store, test_share):
        """list_share_access_logs only returns logs for specified share."""
        # Create another share
        other_share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_456",
            created_by="user_123",
        )

        # Log access to both shares
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
        )
        auth_store.log_share_access(
            share_id=other_share["id"],
            tenant_id="test_tenant",
            access_result="success",
        )

        # Should only get logs for test_share
        logs = auth_store.list_share_access_logs(test_share["id"], "test_tenant")
        assert len(logs) == 1
        assert logs[0]["share_id"] == test_share["id"]


class TestGetShareStats:
    """Tests for get_share_stats."""

    def test_returns_zero_stats_for_no_logs(self, auth_store, test_share):
        """get_share_stats returns zeros when no logs exist."""
        stats = auth_store.get_share_stats(test_share["id"], "test_tenant")

        assert stats["total_accesses"] == 0
        assert stats["successful_accesses"] == 0
        assert stats["denied_accesses"] == 0
        assert stats["unique_ips"] == 0
        assert stats["first_access_at"] is None
        assert stats["last_access_at"] is None

    def test_counts_successful_accesses(self, auth_store, test_share):
        """get_share_stats correctly counts successful accesses."""
        for _ in range(3):
            auth_store.log_share_access(
                share_id=test_share["id"],
                tenant_id="test_tenant",
                access_result="success",
            )

        stats = auth_store.get_share_stats(test_share["id"], "test_tenant")
        assert stats["successful_accesses"] == 3
        assert stats["denied_accesses"] == 0
        assert stats["total_accesses"] == 3

    def test_counts_denied_accesses(self, auth_store, test_share):
        """get_share_stats correctly counts denied accesses."""
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="denied_share_password_invalid",
        )
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="denied_share_expired",
        )

        stats = auth_store.get_share_stats(test_share["id"], "test_tenant")
        assert stats["successful_accesses"] == 0
        assert stats["denied_accesses"] == 2
        assert stats["total_accesses"] == 2

    def test_counts_unique_ips(self, auth_store, test_share):
        """get_share_stats correctly counts unique IP addresses."""
        # Same IP multiple times
        for _ in range(3):
            auth_store.log_share_access(
                share_id=test_share["id"],
                tenant_id="test_tenant",
                access_result="success",
                ip_address="192.168.1.1",
            )
        # Different IP
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
            ip_address="192.168.1.2",
        )

        stats = auth_store.get_share_stats(test_share["id"], "test_tenant")
        assert stats["unique_ips"] == 2

    def test_tracks_first_and_last_access(self, auth_store, test_share):
        """get_share_stats tracks first and last access timestamps."""
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
        )

        stats = auth_store.get_share_stats(test_share["id"], "test_tenant")
        assert stats["first_access_at"] is not None
        assert stats["last_access_at"] is not None

    def test_handles_null_ips(self, auth_store, test_share):
        """get_share_stats handles null IP addresses correctly."""
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
            ip_address=None,
        )
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
            ip_address="192.168.1.1",
        )

        stats = auth_store.get_share_stats(test_share["id"], "test_tenant")
        # Only count non-null IPs
        assert stats["unique_ips"] == 1


class TestCountShareAccessLogs:
    """Tests for count_share_access_logs."""

    def test_returns_zero_for_no_logs(self, auth_store, test_share):
        """count_share_access_logs returns 0 when no logs exist."""
        count = auth_store.count_share_access_logs(test_share["id"], "test_tenant")
        assert count == 0

    def test_returns_correct_count(self, auth_store, test_share):
        """count_share_access_logs returns correct count."""
        for _ in range(7):
            auth_store.log_share_access(
                share_id=test_share["id"],
                tenant_id="test_tenant",
                access_result="success",
            )

        count = auth_store.count_share_access_logs(test_share["id"], "test_tenant")
        assert count == 7

    def test_only_counts_specific_share(self, auth_store, test_share):
        """count_share_access_logs only counts logs for specified share."""
        other_share = auth_store.create_share(
            tenant_id="test_tenant",
            resource_type="run",
            resource_id="run_456",
            created_by="user_123",
        )

        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
        )
        for _ in range(5):
            auth_store.log_share_access(
                share_id=other_share["id"],
                tenant_id="test_tenant",
                access_result="success",
            )

        count = auth_store.count_share_access_logs(test_share["id"], "test_tenant")
        assert count == 1


class TestPruneShareAccessLogs:
    """Tests for prune_share_access_logs."""

    def test_prunes_old_logs(self, auth_store, test_share):
        """prune_share_access_logs removes logs older than threshold."""
        import sqlite3

        # Insert a log with old timestamp directly
        conn = sqlite3.connect(auth_store.db_path)
        cursor = conn.cursor()

        old_timestamp = (datetime.utcnow() - timedelta(days=100)).isoformat()
        cursor.execute(
            """
            INSERT INTO share_access_logs
            (id, share_id, tenant_id, accessed_at, access_result)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("old_log_id", test_share["id"], "test_tenant", old_timestamp, "success"),
        )
        conn.commit()
        conn.close()

        # Add a recent log
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
        )

        # Prune logs older than 90 days
        pruned = auth_store.prune_share_access_logs("test_tenant", older_than_days=90)
        assert pruned == 1

        # Should have 1 log remaining (the recent one)
        count = auth_store.count_share_access_logs(test_share["id"], "test_tenant")
        assert count == 1

    def test_returns_zero_when_no_old_logs(self, auth_store, test_share):
        """prune_share_access_logs returns 0 when no old logs exist."""
        auth_store.log_share_access(
            share_id=test_share["id"],
            tenant_id="test_tenant",
            access_result="success",
        )

        pruned = auth_store.prune_share_access_logs("test_tenant", older_than_days=90)
        assert pruned == 0

    def test_only_prunes_specified_tenant(self, auth_store, test_share):
        """prune_share_access_logs only prunes logs for specified tenant."""
        import sqlite3

        # Create another tenant
        auth_store.create_tenant("other_tenant", "Other Tenant")

        # Insert old logs for both tenants
        conn = sqlite3.connect(auth_store.db_path)
        cursor = conn.cursor()

        old_timestamp = (datetime.utcnow() - timedelta(days=100)).isoformat()
        cursor.execute(
            """
            INSERT INTO share_access_logs
            (id, share_id, tenant_id, accessed_at, access_result)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("old_log_tenant1", test_share["id"], "test_tenant", old_timestamp, "success"),
        )
        cursor.execute(
            """
            INSERT INTO share_access_logs
            (id, share_id, tenant_id, accessed_at, access_result)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("old_log_tenant2", test_share["id"], "other_tenant", old_timestamp, "success"),
        )
        conn.commit()
        conn.close()

        # Prune only test_tenant
        pruned = auth_store.prune_share_access_logs("test_tenant", older_than_days=90)
        assert pruned == 1

        # other_tenant log should still exist
        conn = sqlite3.connect(auth_store.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM share_access_logs WHERE tenant_id = 'other_tenant'")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 1


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
