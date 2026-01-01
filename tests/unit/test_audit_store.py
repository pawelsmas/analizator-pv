"""
Unit tests for audit store (v3.0.0 PR4).

Tests verify:
- Audit log entry creation
- Query filtering
- Export to CSV/JSON
- Tenant isolation
"""

import pytest
import sys
import tempfile
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestAuditStoreBasics:
    """Basic tests for AuditStore."""

    def test_log_returns_entry_id(self):
        """log() should return a UUID entry ID."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        entry_id = store.log(
            tenant_id="tenant_a",
            action="login_success",
            actor_id="user123",
            actor_email="user@example.com",
        )

        assert entry_id is not None
        assert len(entry_id) == 36  # UUID format

    def test_log_with_all_fields(self):
        """log() should accept all optional fields."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        entry_id = store.log(
            tenant_id="tenant_a",
            action="api_key_created",
            actor_id="admin123",
            actor_email="admin@example.com",
            actor_role="admin",
            auth_method="jwt",
            resource_type="api_key",
            resource_id="key-123",
            details={"label": "Test Key", "role": "service"},
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        assert entry_id is not None


class TestAuditStoreQuery:
    """Tests for AuditStore query functionality."""

    def test_query_returns_logged_entries(self):
        """query() should return logged entries."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        store.log(tenant_id="tenant_a", action="login_success", actor_id="user1")
        store.log(tenant_id="tenant_a", action="login_success", actor_id="user2")

        result = store.query(tenant_id="tenant_a")

        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_query_filters_by_action(self):
        """query() should filter by action."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        store.log(tenant_id="tenant_a", action="login_success")
        store.log(tenant_id="tenant_a", action="login_failure")
        store.log(tenant_id="tenant_a", action="login_success")

        result = store.query(tenant_id="tenant_a", action="login_failure")

        assert result["total"] == 1
        assert result["items"][0]["action"] == "login_failure"

    def test_query_filters_by_actor(self):
        """query() should filter by actor_id."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        store.log(tenant_id="tenant_a", action="sizing_run", actor_id="user1")
        store.log(tenant_id="tenant_a", action="sizing_run", actor_id="user2")
        store.log(tenant_id="tenant_a", action="sizing_run", actor_id="user1")

        result = store.query(tenant_id="tenant_a", actor_id="user1")

        assert result["total"] == 2

    def test_query_filters_by_tenant(self):
        """query() should only return entries for specified tenant."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        store.log(tenant_id="tenant_a", action="login_success")
        store.log(tenant_id="tenant_b", action="login_success")
        store.log(tenant_id="tenant_a", action="login_success")

        result_a = store.query(tenant_id="tenant_a")
        result_b = store.query(tenant_id="tenant_b")

        assert result_a["total"] == 2
        assert result_b["total"] == 1

    def test_query_pagination(self):
        """query() should support pagination."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        for i in range(10):
            store.log(tenant_id="tenant_a", action="test", actor_id=f"user{i}")

        page1 = store.query(tenant_id="tenant_a", limit=3, offset=0)
        page2 = store.query(tenant_id="tenant_a", limit=3, offset=3)

        assert page1["total"] == 10
        assert len(page1["items"]) == 3
        assert len(page2["items"]) == 3
        assert page1["items"][0]["id"] != page2["items"][0]["id"]


class TestAuditStoreDetails:
    """Tests for AuditStore details field."""

    def test_details_are_stored_as_json(self):
        """details should be stored and retrieved correctly."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        store.log(
            tenant_id="tenant_a",
            action="api_key_created",
            details={"label": "Test", "role": "service", "count": 42},
        )

        result = store.query(tenant_id="tenant_a")

        assert result["items"][0]["details"]["label"] == "Test"
        assert result["items"][0]["details"]["count"] == 42


class TestAuditStoreExport:
    """Tests for AuditStore export functionality."""

    def test_export_csv_returns_string(self):
        """export_csv() should return CSV string."""
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        store.log(tenant_id="tenant_a", action="login_success", actor_id="user1")

        csv_content = store.export_csv(tenant_id="tenant_a")

        assert "id,tenant_id,created_at,action" in csv_content
        assert "login_success" in csv_content
        assert "user1" in csv_content

    def test_export_json_returns_valid_json(self):
        """export_json() should return valid JSON."""
        import json
        from audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        store.log(tenant_id="tenant_a", action="login_success", actor_id="user1")

        json_content = store.export_json(tenant_id="tenant_a")
        data = json.loads(json_content)

        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["action"] == "login_success"


class TestAuditStorePrune:
    """Tests for AuditStore prune functionality."""

    def test_prune_removes_old_entries(self):
        """prune() should remove entries older than retention period."""
        from audit_store import AuditStore
        from datetime import datetime, timezone, timedelta

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)

        # Log entry
        store.log(tenant_id="tenant_a", action="old_event")

        # Manually update created_at to be old
        import sqlite3
        conn = sqlite3.connect(db_path)
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        conn.execute("UPDATE audit_log SET created_at = ?", (old_date,))
        conn.commit()
        conn.close()

        # Prune with 90 day retention
        deleted = store.prune(retention_days=90)

        assert deleted == 1

        # Verify entry is gone
        result = store.query(tenant_id="tenant_a")
        assert result["total"] == 0
