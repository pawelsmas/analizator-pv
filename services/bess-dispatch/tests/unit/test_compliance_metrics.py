"""
Unit tests for compliance metrics module (v4.3.0 PR10).

Tests:
- Metric recording functions
- Label validation
- Counter/Gauge/Histogram behavior
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestRetentionPolicyMetrics:
    """Tests for retention policy metrics."""

    def test_record_retention_policy_operation_create(self):
        """Test recording retention policy create operation."""
        from observability.compliance_metrics import (
            record_retention_policy_operation,
            RETENTION_POLICY_OPERATIONS_TOTAL,
        )

        # Record operation
        record_retention_policy_operation("create", "tenant", True)

        # Verify counter was incremented
        labels = {"operation": "create", "scope": "tenant", "result": "success"}
        value = RETENTION_POLICY_OPERATIONS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_record_retention_policy_operation_failure(self):
        """Test recording retention policy failure."""
        from observability.compliance_metrics import (
            record_retention_policy_operation,
            RETENTION_POLICY_OPERATIONS_TOTAL,
        )

        record_retention_policy_operation("update", "project", False)

        labels = {"operation": "update", "scope": "project", "result": "failure"}
        value = RETENTION_POLICY_OPERATIONS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_update_retention_policy_days(self):
        """Test updating retention days gauge."""
        from observability.compliance_metrics import (
            update_retention_policy_days,
            RETENTION_POLICY_DAYS,
        )

        update_retention_policy_days("tenant-1", "runs", 365)

        labels = {"tenant_id": "tenant-1", "category": "runs"}
        value = RETENTION_POLICY_DAYS.labels(**labels)._value.get()
        assert value == 365


class TestLegalHoldMetrics:
    """Tests for legal hold metrics."""

    def test_record_legal_hold_operation_create(self):
        """Test recording legal hold create operation."""
        from observability.compliance_metrics import (
            record_legal_hold_operation,
            LEGAL_HOLD_OPERATIONS_TOTAL,
        )

        record_legal_hold_operation("create", "run", True)

        labels = {"operation": "create", "resource_type": "run", "result": "success"}
        value = LEGAL_HOLD_OPERATIONS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_record_legal_hold_operation_release(self):
        """Test recording legal hold release operation."""
        from observability.compliance_metrics import (
            record_legal_hold_operation,
            LEGAL_HOLD_OPERATIONS_TOTAL,
        )

        record_legal_hold_operation("release", "project", True)

        labels = {"operation": "release", "resource_type": "project", "result": "success"}
        value = LEGAL_HOLD_OPERATIONS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_update_legal_hold_count(self):
        """Test updating legal hold count gauge."""
        from observability.compliance_metrics import (
            update_legal_hold_count,
            LEGAL_HOLD_ACTIVE,
        )

        update_legal_hold_count("tenant-1", "run", 5)

        labels = {"tenant_id": "tenant-1", "resource_type": "run"}
        value = LEGAL_HOLD_ACTIVE.labels(**labels)._value.get()
        assert value == 5

    def test_record_legal_hold_check_held(self):
        """Test recording legal hold check when held."""
        from observability.compliance_metrics import (
            record_legal_hold_check,
            LEGAL_HOLD_CHECKS_TOTAL,
        )

        record_legal_hold_check(True)

        value = LEGAL_HOLD_CHECKS_TOTAL.labels(result="held")._value.get()
        assert value >= 1

    def test_record_legal_hold_check_not_held(self):
        """Test recording legal hold check when not held."""
        from observability.compliance_metrics import (
            record_legal_hold_check,
            LEGAL_HOLD_CHECKS_TOTAL,
        )

        record_legal_hold_check(False)

        value = LEGAL_HOLD_CHECKS_TOTAL.labels(result="not_held")._value.get()
        assert value >= 1


class TestPurgeMetrics:
    """Tests for purge metrics."""

    def test_record_purge_run_success(self):
        """Test recording successful purge run."""
        from observability.compliance_metrics import (
            record_purge_run,
            PURGE_RUNS_TOTAL,
        )

        record_purge_run("execute", True, 10.5)

        labels = {"mode": "execute", "result": "success"}
        value = PURGE_RUNS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_record_purge_run_failure(self):
        """Test recording failed purge run."""
        from observability.compliance_metrics import (
            record_purge_run,
            PURGE_RUNS_TOTAL,
        )

        record_purge_run("dry_run", False, 5.0)

        labels = {"mode": "dry_run", "result": "failure"}
        value = PURGE_RUNS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_record_purge_found(self):
        """Test recording resources found for deletion."""
        from observability.compliance_metrics import (
            record_purge_found,
            PURGE_FOUND_TOTAL,
        )

        record_purge_found("runs", 100)

        value = PURGE_FOUND_TOTAL.labels(category="runs")._value.get()
        assert value >= 100

    def test_record_purge_deleted(self):
        """Test recording deleted resources."""
        from observability.compliance_metrics import (
            record_purge_deleted,
            PURGE_DELETED_TOTAL,
        )

        record_purge_deleted("jobs", 50)

        value = PURGE_DELETED_TOTAL.labels(category="jobs")._value.get()
        assert value >= 50

    def test_record_purge_skipped_held(self):
        """Test recording skipped resources due to hold."""
        from observability.compliance_metrics import (
            record_purge_skipped,
            PURGE_SKIPPED_TOTAL,
        )

        record_purge_skipped("runs", "held", 10)

        labels = {"category": "runs", "reason": "held"}
        value = PURGE_SKIPPED_TOTAL.labels(**labels)._value.get()
        assert value >= 10

    def test_record_purge_skipped_error(self):
        """Test recording skipped resources due to error."""
        from observability.compliance_metrics import (
            record_purge_skipped,
            PURGE_SKIPPED_TOTAL,
        )

        record_purge_skipped("reports", "error", 5)

        labels = {"category": "reports", "reason": "error"}
        value = PURGE_SKIPPED_TOTAL.labels(**labels)._value.get()
        assert value >= 5

    def test_record_purge_hit_limit(self):
        """Test recording purge hit limit."""
        from observability.compliance_metrics import (
            record_purge_hit_limit,
            PURGE_HIT_LIMIT_TOTAL,
        )

        record_purge_hit_limit("execute")

        value = PURGE_HIT_LIMIT_TOTAL.labels(mode="execute")._value.get()
        assert value >= 1


class TestComplianceExportMetrics:
    """Tests for compliance export metrics."""

    def test_record_compliance_export_operation_create(self):
        """Test recording export create operation."""
        from observability.compliance_metrics import (
            record_compliance_export_operation,
            COMPLIANCE_EXPORT_OPERATIONS_TOTAL,
        )

        record_compliance_export_operation("create", True)

        labels = {"operation": "create", "result": "success"}
        value = COMPLIANCE_EXPORT_OPERATIONS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_record_compliance_export_operation_download(self):
        """Test recording export download operation."""
        from observability.compliance_metrics import (
            record_compliance_export_operation,
            COMPLIANCE_EXPORT_OPERATIONS_TOTAL,
        )

        record_compliance_export_operation("download", True)

        labels = {"operation": "download", "result": "success"}
        value = COMPLIANCE_EXPORT_OPERATIONS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_record_compliance_export_operation_failure(self):
        """Test recording export operation failure."""
        from observability.compliance_metrics import (
            record_compliance_export_operation,
            COMPLIANCE_EXPORT_OPERATIONS_TOTAL,
        )

        record_compliance_export_operation("delete", False)

        labels = {"operation": "delete", "result": "failure"}
        value = COMPLIANCE_EXPORT_OPERATIONS_TOTAL.labels(**labels)._value.get()
        assert value >= 1

    def test_update_compliance_export_status(self):
        """Test updating export status gauge."""
        from observability.compliance_metrics import (
            update_compliance_export_status,
            COMPLIANCE_EXPORT_STATUS,
        )

        update_compliance_export_status("tenant-1", "pending", 3)

        labels = {"tenant_id": "tenant-1", "status": "pending"}
        value = COMPLIANCE_EXPORT_STATUS.labels(**labels)._value.get()
        assert value == 3

    def test_record_compliance_export_size(self):
        """Test recording export size."""
        from observability.compliance_metrics import (
            record_compliance_export_size,
            COMPLIANCE_EXPORT_SIZE_BYTES,
        )

        # Record multiple observations
        record_compliance_export_size(1024)
        record_compliance_export_size(2048)

        # Check histogram has observations
        assert COMPLIANCE_EXPORT_SIZE_BYTES._sum.get() >= 3072

    def test_record_compliance_export_records(self):
        """Test recording export record count."""
        from observability.compliance_metrics import (
            record_compliance_export_records,
            COMPLIANCE_EXPORT_RECORDS,
        )

        record_compliance_export_records(100)
        record_compliance_export_records(200)

        assert COMPLIANCE_EXPORT_RECORDS._sum.get() >= 300

    def test_record_compliance_export_duration(self):
        """Test recording export duration."""
        from observability.compliance_metrics import (
            record_compliance_export_duration,
            COMPLIANCE_EXPORT_DURATION_SECONDS,
        )

        record_compliance_export_duration(10.5)
        record_compliance_export_duration(20.3)

        assert COMPLIANCE_EXPORT_DURATION_SECONDS._sum.get() >= 30.0


class TestMetricLabels:
    """Tests for metric label validation."""

    def test_purge_mode_labels(self):
        """Test purge mode labels are valid."""
        from observability.compliance_metrics import PURGE_RUNS_TOTAL

        # These should not raise
        PURGE_RUNS_TOTAL.labels(mode="dry_run", result="success")
        PURGE_RUNS_TOTAL.labels(mode="execute", result="failure")

    def test_legal_hold_resource_type_labels(self):
        """Test legal hold resource type labels."""
        from observability.compliance_metrics import LEGAL_HOLD_OPERATIONS_TOTAL

        # These should not raise
        LEGAL_HOLD_OPERATIONS_TOTAL.labels(operation="create", resource_type="project", result="success")
        LEGAL_HOLD_OPERATIONS_TOTAL.labels(operation="release", resource_type="run", result="failure")
        LEGAL_HOLD_OPERATIONS_TOTAL.labels(operation="create", resource_type="job", result="success")
        LEGAL_HOLD_OPERATIONS_TOTAL.labels(operation="create", resource_type="all", result="success")

    def test_retention_category_labels(self):
        """Test retention category labels."""
        from observability.compliance_metrics import PURGE_DELETED_TOTAL

        # These should not raise
        for category in ["runs", "jobs", "reports", "audit_logs", "exports"]:
            PURGE_DELETED_TOTAL.labels(category=category)
