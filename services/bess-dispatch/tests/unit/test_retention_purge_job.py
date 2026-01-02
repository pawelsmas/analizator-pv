"""
Unit tests for retention purge job module (v4.3.0 PR9).

Tests:
- Configuration loading from environment
- Tenant listing and iteration
- Purge execution with notifications
- Metrics push to Pushgateway
"""

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_store import ComplianceStore
from retention_policy_helper import ResourceCategory
from retention_executor import PurgeResult, PurgeStats


class TestGetEnabledCategories:
    """Tests for get_enabled_categories function."""

    def test_default_all_categories(self):
        """Test default returns all categories."""
        from retention_purge_job import get_enabled_categories

        with patch.dict(os.environ, {"ENABLED_CATEGORIES": ""}, clear=False):
            categories = get_enabled_categories()
            assert len(categories) == len(list(ResourceCategory))

    def test_specific_categories(self):
        """Test parsing specific categories."""
        from retention_purge_job import get_enabled_categories

        with patch.dict(os.environ, {"ENABLED_CATEGORIES": "runs,jobs"}, clear=False):
            categories = get_enabled_categories()
            assert ResourceCategory.RUNS in categories
            assert ResourceCategory.JOBS in categories
            assert len(categories) == 2

    def test_ignore_unknown_categories(self):
        """Test unknown categories are ignored."""
        from retention_purge_job import get_enabled_categories

        with patch.dict(os.environ, {"ENABLED_CATEGORIES": "runs,unknown,jobs"}, clear=False):
            categories = get_enabled_categories()
            assert len(categories) == 2

    def test_case_insensitive(self):
        """Test category names are case insensitive."""
        from retention_purge_job import get_enabled_categories

        with patch.dict(os.environ, {"ENABLED_CATEGORIES": "Runs,JOBS"}, clear=False):
            categories = get_enabled_categories()
            assert ResourceCategory.RUNS in categories
            assert ResourceCategory.JOBS in categories


class TestSendSlackNotification:
    """Tests for send_slack_notification function."""

    @patch("retention_purge_job.urlopen")
    def test_send_success_notification(self, mock_urlopen):
        """Test sending success notification."""
        from retention_purge_job import send_slack_notification

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = PurgeResult(
            mode="execute",
            tenant_id="t1",
            started_at=datetime.now(timezone.utc).isoformat(),
            success=True,
            total_found=100,
            total_to_delete=50,
            total_deleted=50,
        )

        success = send_slack_notification(
            "https://hooks.slack.com/test",
            result,
            "t1",
            10.5,
        )

        assert success is True
        mock_urlopen.assert_called_once()

    @patch("retention_purge_job.urlopen")
    def test_send_failure_notification(self, mock_urlopen):
        """Test sending failure notification."""
        from retention_purge_job import send_slack_notification

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = PurgeResult(
            mode="execute",
            tenant_id="t1",
            started_at=datetime.now(timezone.utc).isoformat(),
            success=False,
            error="Database connection failed",
        )

        success = send_slack_notification(
            "https://hooks.slack.com/test",
            result,
            "t1",
            5.0,
        )

        assert success is True

    @patch("retention_purge_job.urlopen")
    def test_notification_with_hit_limit(self, mock_urlopen):
        """Test notification includes hit limit warning."""
        from retention_purge_job import send_slack_notification

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = PurgeResult(
            mode="execute",
            tenant_id="t1",
            started_at=datetime.now(timezone.utc).isoformat(),
            success=True,
            total_deleted=1000,
            hit_limit=True,
        )

        success = send_slack_notification(
            "https://hooks.slack.com/test",
            result,
            "t1",
            30.0,
        )

        assert success is True

    @patch("retention_purge_job.urlopen")
    def test_notification_error_handling(self, mock_urlopen):
        """Test notification handles errors gracefully."""
        from retention_purge_job import send_slack_notification

        mock_urlopen.side_effect = Exception("Connection refused")

        result = PurgeResult(
            mode="execute",
            tenant_id="t1",
            started_at=datetime.now(timezone.utc).isoformat(),
            success=True,
        )

        success = send_slack_notification(
            "https://hooks.slack.com/test",
            result,
            "t1",
            5.0,
        )

        assert success is False


class TestPushMetricsToPushgateway:
    """Tests for push_metrics_to_pushgateway function."""

    @patch("retention_purge_job.urlopen")
    def test_push_metrics_success(self, mock_urlopen):
        """Test pushing metrics successfully."""
        from retention_purge_job import push_metrics_to_pushgateway

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = PurgeResult(
            mode="execute",
            tenant_id="t1",
            started_at=datetime.now(timezone.utc).isoformat(),
            success=True,
            total_found=100,
            total_to_delete=50,
            total_deleted=50,
            total_skipped_held=5,
            total_skipped_error=0,
            categories=[
                PurgeStats(category="runs", retention_days=365, total_found=100, deleted=50, skipped_held=5),
            ],
        )

        success = push_metrics_to_pushgateway(
            "http://pushgateway:9091",
            result,
            "t1",
        )

        assert success is True
        mock_urlopen.assert_called_once()

    @patch("retention_purge_job.urlopen")
    def test_push_metrics_error_handling(self, mock_urlopen):
        """Test metrics push handles errors gracefully."""
        from retention_purge_job import push_metrics_to_pushgateway

        mock_urlopen.side_effect = Exception("Connection refused")

        result = PurgeResult(
            mode="execute",
            tenant_id="t1",
            started_at=datetime.now(timezone.utc).isoformat(),
            success=True,
        )

        success = push_metrics_to_pushgateway(
            "http://pushgateway:9091",
            result,
            "t1",
        )

        assert success is False


class TestRunPurgeForTenant:
    """Tests for run_purge_for_tenant function."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.fixture
    def store(self, temp_db):
        """Create a ComplianceStore with temporary database."""
        return ComplianceStore(db_path=temp_db)

    def test_dry_run_mode(self, store):
        """Test running in dry-run mode."""
        from retention_purge_job import run_purge_for_tenant

        store.create_retention_policy("t1", {"runs_days": 365})

        result = run_purge_for_tenant(
            store,
            tenant_id="t1",
            dry_run=True,
        )

        assert result.mode == "dry_run"
        assert result.success is True

    def test_execute_mode(self, store):
        """Test running in execute mode (uses default max_deletions)."""
        from retention_purge_job import run_purge_for_tenant

        store.create_retention_policy("t1", {"runs_days": 365})

        result = run_purge_for_tenant(
            store,
            tenant_id="t1",
            dry_run=False,
        )

        assert result.mode == "execute"
        assert result.success is True

    def test_with_max_deletions(self, store):
        """Test running with max deletions limit."""
        from retention_purge_job import run_purge_for_tenant

        store.create_retention_policy("t1", {"runs_days": 365})

        result = run_purge_for_tenant(
            store,
            tenant_id="t1",
            dry_run=False,
            max_deletions=100,
        )

        assert result.success is True

    def test_with_specific_categories(self, store):
        """Test running with specific categories."""
        from retention_purge_job import run_purge_for_tenant

        store.create_retention_policy("t1", {"runs_days": 365, "jobs_days": 90})

        result = run_purge_for_tenant(
            store,
            tenant_id="t1",
            dry_run=True,
            categories=[ResourceCategory.RUNS],
        )

        assert result.success is True
        # Only runs category should be processed
        category_names = [c.category for c in result.categories]
        assert "runs" in category_names


class TestListTenantsWithPolicies:
    """Tests for list_tenants_with_policies method."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.fixture
    def store(self, temp_db):
        """Create a ComplianceStore with temporary database."""
        return ComplianceStore(db_path=temp_db)

    def test_no_tenants(self, store):
        """Test with no tenants."""
        tenants = store.list_tenants_with_policies()
        assert tenants == []

    def test_single_tenant(self, store):
        """Test with single tenant."""
        store.create_retention_policy("t1", {"runs_days": 365})

        tenants = store.list_tenants_with_policies()
        assert tenants == ["t1"]

    def test_multiple_tenants(self, store):
        """Test with multiple tenants."""
        store.create_retention_policy("t1", {"runs_days": 365})
        store.create_retention_policy("t2", {"runs_days": 180})
        store.create_retention_policy("t3", {"runs_days": 90})

        tenants = store.list_tenants_with_policies()
        assert len(tenants) == 3
        assert "t1" in tenants
        assert "t2" in tenants
        assert "t3" in tenants

    def test_excludes_disabled_policies(self, store):
        """Test that disabled policies are excluded."""
        store.create_retention_policy("t1", {"runs_days": 365})
        store.create_retention_policy("t2", {"runs_days": 180})

        # Disable t2's policy
        conn = store._get_conn()
        try:
            conn.execute(
                "UPDATE retention_policies SET enabled = 0 WHERE tenant_id = ?",
                ("t2",)
            )
            conn.commit()
        finally:
            conn.close()

        tenants = store.list_tenants_with_policies()
        assert tenants == ["t1"]

    def test_unique_tenants(self, store):
        """Test that tenants are unique even with project policies."""
        store.create_retention_policy("t1", {"runs_days": 365})
        store.create_retention_policy("t1", {"runs_days": 180}, project_id="proj-1")
        store.create_retention_policy("t1", {"runs_days": 90}, project_id="proj-2")

        tenants = store.list_tenants_with_policies()
        assert tenants == ["t1"]
