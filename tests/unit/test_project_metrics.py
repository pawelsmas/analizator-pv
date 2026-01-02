"""
Unit tests for Project metrics (v3.7.0 PR6).

Tests for observability/project_metrics.py.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add bess-dispatch to path
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))


class TestProjectMetricsModule:
    """Tests for project_metrics module existence and structure."""

    def test_module_exists(self):
        """project_metrics.py should exist."""
        path = BESS_DIR / "observability" / "project_metrics.py"
        assert path.exists(), "project_metrics.py should exist"

    def test_module_imports(self):
        """Module should be importable."""
        from observability import project_metrics
        assert project_metrics is not None

    def test_counter_metrics_defined(self):
        """Required counter metrics should be defined."""
        from observability import project_metrics

        assert hasattr(project_metrics, "PROJECT_OPERATIONS_TOTAL")
        assert hasattr(project_metrics, "PROJECT_MEMBERSHIP_OPERATIONS_TOTAL")
        assert hasattr(project_metrics, "PROJECT_ACCESS_CHECKS_TOTAL")
        assert hasattr(project_metrics, "PROJECT_ACCESS_DENIED_TOTAL")
        assert hasattr(project_metrics, "PROJECT_SHARE_POLICY_ENFORCEMENTS_TOTAL")
        assert hasattr(project_metrics, "PROJECT_RESOURCE_ACCESS_TOTAL")

    def test_gauge_metrics_defined(self):
        """Required gauge metrics should be defined."""
        from observability import project_metrics

        assert hasattr(project_metrics, "PROJECT_COUNT")
        assert hasattr(project_metrics, "PROJECT_MEMBERSHIP_COUNT")

    def test_histogram_metrics_defined(self):
        """Required histogram metrics should be defined."""
        from observability import project_metrics

        assert hasattr(project_metrics, "PROJECT_MEMBERSHIP_CHANGES_HISTOGRAM")


class TestProjectOperationsMetric:
    """Tests for project CRUD operations counter."""

    def test_metric_has_correct_labels(self):
        """PROJECT_OPERATIONS_TOTAL should have operation and result labels."""
        from observability.project_metrics import PROJECT_OPERATIONS_TOTAL

        labels = PROJECT_OPERATIONS_TOTAL._labelnames
        assert "operation" in labels
        assert "result" in labels

    def test_record_project_operation_success(self):
        """record_project_operation should increment counter for success."""
        from observability.project_metrics import record_project_operation

        # Should not raise
        record_project_operation("create", True)
        record_project_operation("update", True)
        record_project_operation("archive", True)
        record_project_operation("list", True)

    def test_record_project_operation_failure(self):
        """record_project_operation should increment counter for failure."""
        from observability.project_metrics import record_project_operation

        # Should not raise
        record_project_operation("create", False)
        record_project_operation("update", False)


class TestMembershipOperationsMetric:
    """Tests for membership operations counter."""

    def test_metric_has_correct_labels(self):
        """PROJECT_MEMBERSHIP_OPERATIONS_TOTAL should have operation, role, result labels."""
        from observability.project_metrics import PROJECT_MEMBERSHIP_OPERATIONS_TOTAL

        labels = PROJECT_MEMBERSHIP_OPERATIONS_TOTAL._labelnames
        assert "operation" in labels
        assert "role" in labels
        assert "result" in labels

    def test_record_membership_operation(self):
        """record_membership_operation should increment counter."""
        from observability.project_metrics import record_membership_operation

        # Should not raise
        record_membership_operation("add", "owner", True)
        record_membership_operation("add", "editor", True)
        record_membership_operation("add", "viewer", True)
        record_membership_operation("update", "editor", True)
        record_membership_operation("remove", "viewer", True)


class TestAccessChecksMetric:
    """Tests for project access checks counter."""

    def test_metric_has_correct_labels(self):
        """PROJECT_ACCESS_CHECKS_TOTAL should have required_role and result labels."""
        from observability.project_metrics import PROJECT_ACCESS_CHECKS_TOTAL

        labels = PROJECT_ACCESS_CHECKS_TOTAL._labelnames
        assert "required_role" in labels
        assert "result" in labels

    def test_record_project_access_check_allowed(self):
        """record_project_access_check should handle allowed case."""
        from observability.project_metrics import record_project_access_check

        # Should not raise
        record_project_access_check("owner", True)
        record_project_access_check("editor", True)
        record_project_access_check("viewer", True)

    def test_record_project_access_check_denied(self):
        """record_project_access_check should handle denied case."""
        from observability.project_metrics import record_project_access_check

        # Should not raise
        record_project_access_check("owner", False)
        record_project_access_check("editor", False)


class TestAccessDeniedMetric:
    """Tests for project access denied counter (forbidden spikes)."""

    def test_metric_has_correct_labels(self):
        """PROJECT_ACCESS_DENIED_TOTAL should have reason label."""
        from observability.project_metrics import PROJECT_ACCESS_DENIED_TOTAL

        labels = PROJECT_ACCESS_DENIED_TOTAL._labelnames
        assert "reason" in labels

    def test_record_project_access_denied(self):
        """record_project_access_denied should increment counter with reasons."""
        from observability.project_metrics import record_project_access_denied

        # Should not raise
        record_project_access_denied("not_member")
        record_project_access_denied("insufficient_role")
        record_project_access_denied("project_archived")
        record_project_access_denied("project_not_found")


class TestSharePolicyEnforcementsMetric:
    """Tests for share policy enforcement counter."""

    def test_metric_has_correct_labels(self):
        """PROJECT_SHARE_POLICY_ENFORCEMENTS_TOTAL should have policy and enforcement_result labels."""
        from observability.project_metrics import PROJECT_SHARE_POLICY_ENFORCEMENTS_TOTAL

        labels = PROJECT_SHARE_POLICY_ENFORCEMENTS_TOTAL._labelnames
        assert "policy" in labels
        assert "enforcement_result" in labels

    def test_record_share_policy_enforcement(self):
        """record_share_policy_enforcement should handle all result types."""
        from observability.project_metrics import record_share_policy_enforcement

        # Should not raise
        record_share_policy_enforcement("allow_public_shares", "allowed")
        record_share_policy_enforcement("allow_public_shares", "denied")
        record_share_policy_enforcement("share_max_expiry", "allowed")
        record_share_policy_enforcement("share_max_expiry", "clamped")


class TestGaugeMetrics:
    """Tests for gauge metrics."""

    def test_set_project_count(self):
        """set_project_count should set gauge value."""
        from observability.project_metrics import set_project_count

        # Should not raise
        set_project_count("tenant_123", 5)
        set_project_count("tenant_456", 10)

    def test_set_membership_count(self):
        """set_membership_count should set gauge value."""
        from observability.project_metrics import set_membership_count

        # Should not raise
        set_membership_count("proj_123", 3)
        set_membership_count("proj_456", 7)


class TestResourceAccessMetric:
    """Tests for project resource access counter."""

    def test_metric_has_correct_labels(self):
        """PROJECT_RESOURCE_ACCESS_TOTAL should have resource_type, operation, result labels."""
        from observability.project_metrics import PROJECT_RESOURCE_ACCESS_TOTAL

        labels = PROJECT_RESOURCE_ACCESS_TOTAL._labelnames
        assert "resource_type" in labels
        assert "operation" in labels
        assert "result" in labels

    def test_record_project_resource_access(self):
        """record_project_resource_access should increment counter."""
        from observability.project_metrics import record_project_resource_access

        # Should not raise
        record_project_resource_access("run", "read", True)
        record_project_resource_access("run", "write", True)
        record_project_resource_access("job", "read", False)
        record_project_resource_access("report", "read", True)


class TestHistogramMetrics:
    """Tests for histogram metrics."""

    def test_observe_membership_changes(self):
        """observe_membership_changes should observe values."""
        from observability.project_metrics import observe_membership_changes

        # Should not raise
        observe_membership_changes("add", 1)
        observe_membership_changes("add", 5)
        observe_membership_changes("remove", 2)


class TestHelperFunctionsExist:
    """Tests that all helper functions exist."""

    def test_all_helper_functions_defined(self):
        """All helper functions should be defined."""
        from observability import project_metrics

        assert hasattr(project_metrics, "record_project_operation")
        assert hasattr(project_metrics, "record_membership_operation")
        assert hasattr(project_metrics, "record_project_access_check")
        assert hasattr(project_metrics, "record_project_access_denied")
        assert hasattr(project_metrics, "record_share_policy_enforcement")
        assert hasattr(project_metrics, "set_project_count")
        assert hasattr(project_metrics, "set_membership_count")
        assert hasattr(project_metrics, "record_project_resource_access")
        assert hasattr(project_metrics, "observe_membership_changes")

    def test_helper_functions_callable(self):
        """All helper functions should be callable."""
        from observability import project_metrics

        assert callable(project_metrics.record_project_operation)
        assert callable(project_metrics.record_membership_operation)
        assert callable(project_metrics.record_project_access_check)
        assert callable(project_metrics.record_project_access_denied)
        assert callable(project_metrics.record_share_policy_enforcement)
        assert callable(project_metrics.set_project_count)
        assert callable(project_metrics.set_membership_count)
        assert callable(project_metrics.record_project_resource_access)
        assert callable(project_metrics.observe_membership_changes)


class TestAlertsDocumentation:
    """Tests for ALERTS.md updates."""

    @pytest.fixture
    def alerts_doc(self):
        """Load ALERTS.md content."""
        path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        return path.read_text(encoding="utf-8")

    def test_project_alerts_section_exists(self, alerts_doc):
        """ALERTS.md should have Projects & RBAC section."""
        assert "## Projects & RBAC Alerts (v3.7.0)" in alerts_doc

    def test_access_denied_spike_alert(self, alerts_doc):
        """ALERTS.md should have access denied spike alert."""
        assert "BESSProjectAccessDeniedSpike" in alerts_doc

    def test_forbidden_rate_alert(self, alerts_doc):
        """ALERTS.md should have project forbidden rate alert."""
        assert "BESSProjectForbiddenRateHigh" in alerts_doc

    def test_share_policy_denials_alert(self, alerts_doc):
        """ALERTS.md should have share policy denials alert."""
        assert "BESSSharePolicyDenials" in alerts_doc

    def test_share_policy_clamping_alert(self, alerts_doc):
        """ALERTS.md should have share policy clamping alert."""
        assert "BESSSharePolicyClamping" in alerts_doc

    def test_membership_activity_alert(self, alerts_doc):
        """ALERTS.md should have membership activity alert."""
        assert "BESSProjectMembershipActivity" in alerts_doc

    def test_non_member_access_alert(self, alerts_doc):
        """ALERTS.md should have non-member access alert."""
        assert "BESSNonMemberAccessAttempts" in alerts_doc

    def test_project_creation_rate_alert(self, alerts_doc):
        """ALERTS.md should have project creation rate alert."""
        assert "BESSProjectCreationRate" in alerts_doc

    def test_cross_project_access_alert(self, alerts_doc):
        """ALERTS.md should have cross-project access alert."""
        assert "BESSCrossProjectAccessDenied" in alerts_doc


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
