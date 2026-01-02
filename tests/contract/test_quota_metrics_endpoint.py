"""
Contract tests for quota metrics endpoint.

Tests verify:
- /metrics endpoint exposes quota metrics
- Metrics have correct format and labels
- Metric values update correctly after operations
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from prometheus_client import REGISTRY, generate_latest


# -----------------------------------------------------------------------------
# Metric export tests
# -----------------------------------------------------------------------------

class TestQuotaMetricsExport:
    """Tests for quota metrics export."""

    def test_can_generate_metrics_output(self):
        """Should be able to generate metrics output."""
        output = generate_latest(REGISTRY)
        assert output is not None
        assert len(output) > 0

    def test_output_is_prometheus_format(self):
        """Output should be in Prometheus text format."""
        output = generate_latest(REGISTRY).decode("utf-8")
        # Should contain TYPE and HELP comments
        assert "# TYPE" in output or "# HELP" in output

    def test_quota_check_metric_exists(self):
        """Should have bess_quota_check metric."""
        from observability.quota_metrics import record_quota_check
        record_quota_check("jobs_per_day", allowed=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_check" in output

    def test_quota_exceeded_metric_exists(self):
        """Should have bess_quota_exceeded metric."""
        from observability.quota_metrics import record_quota_exceeded
        record_quota_exceeded("jobs_per_day", "free")

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_exceeded" in output

    def test_quota_enforcement_metric_exists(self):
        """Should have bess_quota_enforcement metric."""
        from observability.quota_metrics import record_quota_enforcement
        record_quota_enforcement("jobs_per_day", "blocked")

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_enforcement" in output

    def test_quota_usage_current_metric_exists(self):
        """Should have bess_quota_usage_current metric."""
        from observability.quota_metrics import update_quota_usage
        update_quota_usage("test-tenant", "test-project", "jobs_per_day", 5, 10)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_usage_current" in output

    def test_quota_limit_current_metric_exists(self):
        """Should have bess_quota_limit_current metric."""
        from observability.quota_metrics import update_quota_usage
        update_quota_usage("test-tenant-2", "test-project-2", "jobs_per_day", 5, 10)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_limit_current" in output

    def test_quota_usage_pct_metric_exists(self):
        """Should have bess_quota_usage_pct metric."""
        from observability.quota_metrics import update_quota_usage
        update_quota_usage("test-tenant-3", "test-project-3", "jobs_per_day", 5, 10)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_usage_pct" in output

    def test_quota_remaining_metric_exists(self):
        """Should have bess_quota_remaining metric."""
        from observability.quota_metrics import update_quota_usage
        update_quota_usage("test-tenant-4", "test-project-4", "jobs_per_day", 5, 10)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_remaining" in output

    def test_usage_api_requests_metric_exists(self):
        """Should have bess_usage_api_requests metric."""
        from observability.quota_metrics import record_usage_api_request
        record_usage_api_request("tenant", success=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_usage_api_requests" in output

    def test_usage_export_metric_exists(self):
        """Should have bess_usage_export metric."""
        from observability.quota_metrics import record_usage_export
        record_usage_export("csv", success=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_usage_export" in output

    def test_plan_assignments_metric_exists(self):
        """Should have bess_plan_assignments metric."""
        from observability.quota_metrics import record_plan_assignment
        record_plan_assignment("pro", is_new=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_plan_assignments" in output

    def test_project_override_metric_exists(self):
        """Should have bess_project_override metric."""
        from observability.quota_metrics import record_project_override
        record_project_override("jobs_per_day", is_set=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_project_override" in output

    def test_plan_usage_by_tier_metric_exists(self):
        """Should have bess_plan_usage_by_tier metric."""
        from observability.quota_metrics import update_plan_tier_usage
        update_plan_tier_usage({"free": 10, "pro": 5})

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_plan_usage_by_tier" in output

    def test_quota_reset_seconds_metric_exists(self):
        """Should have bess_quota_reset_seconds_remaining metric."""
        from observability.quota_metrics import update_quota_reset_seconds
        update_quota_reset_seconds(3600)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_quota_reset_seconds_remaining" in output

    def test_usage_query_duration_metric_exists(self):
        """Should have bess_usage_query_duration_seconds metric."""
        from observability.quota_metrics import observe_usage_query_duration
        observe_usage_query_duration("tenant_summary", 0.05)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert "bess_usage_query_duration_seconds" in output


# -----------------------------------------------------------------------------
# Label value tests
# -----------------------------------------------------------------------------

class TestQuotaMetricLabels:
    """Tests for quota metric label values."""

    def test_quota_check_has_quota_name_label(self):
        """Should have quota_name in output."""
        from observability.quota_metrics import record_quota_check
        record_quota_check("reports_per_day", allowed=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'quota_name="reports_per_day"' in output

    def test_quota_check_has_result_label(self):
        """Should have result in output."""
        from observability.quota_metrics import record_quota_check
        record_quota_check("shares_total", allowed=False)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'result="denied"' in output

    def test_quota_exceeded_has_plan_id_label(self):
        """Should have plan_id in output."""
        from observability.quota_metrics import record_quota_exceeded
        record_quota_exceeded("storage_mb", "enterprise")

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'plan_id="enterprise"' in output

    def test_quota_usage_has_tenant_label(self):
        """Should have tenant_id in output."""
        from observability.quota_metrics import update_quota_usage
        update_quota_usage("my-tenant-label", "my-project-label", "jobs_per_day", 7, 20)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'tenant_id="my-tenant-label"' in output
        assert 'project_id="my-project-label"' in output

    def test_usage_api_has_endpoint_label(self):
        """Should have endpoint in output."""
        from observability.quota_metrics import record_usage_api_request
        record_usage_api_request("daily", success=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'endpoint="daily"' in output

    def test_usage_export_has_format_label(self):
        """Should have format in output."""
        from observability.quota_metrics import record_usage_export
        record_usage_export("json", success=True)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'format="json"' in output

    def test_plan_assignments_has_operation_label(self):
        """Should have operation in output."""
        from observability.quota_metrics import record_plan_assignment
        record_plan_assignment("enterprise", is_new=False)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'operation="change"' in output

    def test_project_override_has_operation_label(self):
        """Should have operation in output."""
        from observability.quota_metrics import record_project_override
        record_project_override("storage_mb", is_set=False)

        output = generate_latest(REGISTRY).decode("utf-8")
        assert 'operation="clear"' in output


# -----------------------------------------------------------------------------
# Metric value tests
# -----------------------------------------------------------------------------

class TestQuotaMetricValues:
    """Tests for quota metric values."""

    def test_quota_usage_pct_calculates_correctly(self):
        """Should calculate percentage correctly."""
        from observability.quota_metrics import QUOTA_USAGE_PCT, update_quota_usage

        update_quota_usage("pct-tenant", "pct-project", "jobs_per_day", 50, 100)

        # Get the metric value
        labels = {"tenant_id": "pct-tenant", "project_id": "pct-project", "quota_name": "jobs_per_day"}
        value = QUOTA_USAGE_PCT.labels(**labels)._value.get()

        assert value == 50.0  # 50%

    def test_quota_remaining_calculates_correctly(self):
        """Should calculate remaining correctly."""
        from observability.quota_metrics import QUOTA_REMAINING, update_quota_usage

        update_quota_usage("rem-tenant", "rem-project", "jobs_per_day", 30, 100)

        labels = {"tenant_id": "rem-tenant", "project_id": "rem-project", "quota_name": "jobs_per_day"}
        value = QUOTA_REMAINING.labels(**labels)._value.get()

        assert value == 70  # 100 - 30

    def test_quota_remaining_zero_when_exceeded(self):
        """Should return 0 when exceeded."""
        from observability.quota_metrics import QUOTA_REMAINING, update_quota_usage

        update_quota_usage("exc-tenant", "exc-project", "jobs_per_day", 120, 100)

        labels = {"tenant_id": "exc-tenant", "project_id": "exc-project", "quota_name": "jobs_per_day"}
        value = QUOTA_REMAINING.labels(**labels)._value.get()

        assert value == 0

    def test_quota_remaining_negative_one_when_unlimited(self):
        """Should return -1 when unlimited."""
        from observability.quota_metrics import QUOTA_REMAINING, update_quota_usage

        update_quota_usage("unl-tenant", "unl-project", "jobs_per_day", 50, 0)

        labels = {"tenant_id": "unl-tenant", "project_id": "unl-project", "quota_name": "jobs_per_day"}
        value = QUOTA_REMAINING.labels(**labels)._value.get()

        assert value == -1

    def test_plan_usage_by_tier_sets_correctly(self):
        """Should set tier counts correctly."""
        from observability.quota_metrics import PLAN_USAGE_BY_TIER, update_plan_tier_usage

        update_plan_tier_usage({"free": 42, "pro": 17})

        free_value = PLAN_USAGE_BY_TIER.labels(plan_id="free")._value.get()
        pro_value = PLAN_USAGE_BY_TIER.labels(plan_id="pro")._value.get()

        assert free_value == 42
        assert pro_value == 17

    def test_quota_reset_seconds_sets_correctly(self):
        """Should set reset seconds correctly."""
        from observability.quota_metrics import QUOTA_RESET_SECONDS_REMAINING, update_quota_reset_seconds

        update_quota_reset_seconds(12345)

        value = QUOTA_RESET_SECONDS_REMAINING._value.get()
        assert value == 12345

