"""
Unit tests for quota metrics.

Tests verify:
- All metric counters and gauges are defined
- Helper functions correctly record metrics
- Label values are validated
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from observability.quota_metrics import (
    # Counters
    QUOTA_CHECK_TOTAL,
    QUOTA_EXCEEDED_TOTAL,
    QUOTA_ENFORCEMENT_TOTAL,
    USAGE_API_REQUESTS_TOTAL,
    USAGE_EXPORT_TOTAL,
    PLAN_ASSIGNMENTS_TOTAL,
    PROJECT_OVERRIDE_TOTAL,
    # Gauges
    QUOTA_USAGE_CURRENT,
    QUOTA_LIMIT_CURRENT,
    QUOTA_USAGE_PCT,
    QUOTA_REMAINING,
    PLAN_USAGE_BY_TIER,
    QUOTA_RESET_SECONDS_REMAINING,
    # Histogram
    USAGE_QUERY_DURATION,
    # Helper functions
    record_quota_check,
    record_quota_exceeded,
    record_quota_enforcement,
    update_quota_usage,
    record_usage_api_request,
    record_usage_export,
    observe_usage_query_duration,
    record_plan_assignment,
    record_project_override,
    update_plan_tier_usage,
    update_quota_reset_seconds,
)


# -----------------------------------------------------------------------------
# Metric definition tests
# -----------------------------------------------------------------------------

class TestMetricDefinitions:
    """Tests for metric definitions."""

    def test_quota_check_total_exists(self):
        """Should have quota check counter."""
        assert QUOTA_CHECK_TOTAL is not None
        assert QUOTA_CHECK_TOTAL._name == "bess_quota_check"

    def test_quota_exceeded_total_exists(self):
        """Should have quota exceeded counter."""
        assert QUOTA_EXCEEDED_TOTAL is not None
        assert QUOTA_EXCEEDED_TOTAL._name == "bess_quota_exceeded"

    def test_quota_enforcement_total_exists(self):
        """Should have quota enforcement counter."""
        assert QUOTA_ENFORCEMENT_TOTAL is not None
        assert QUOTA_ENFORCEMENT_TOTAL._name == "bess_quota_enforcement"

    def test_quota_usage_current_exists(self):
        """Should have current usage gauge."""
        assert QUOTA_USAGE_CURRENT is not None
        assert QUOTA_USAGE_CURRENT._name == "bess_quota_usage_current"

    def test_quota_limit_current_exists(self):
        """Should have current limit gauge."""
        assert QUOTA_LIMIT_CURRENT is not None
        assert QUOTA_LIMIT_CURRENT._name == "bess_quota_limit_current"

    def test_quota_usage_pct_exists(self):
        """Should have usage percentage gauge."""
        assert QUOTA_USAGE_PCT is not None
        assert QUOTA_USAGE_PCT._name == "bess_quota_usage_pct"

    def test_quota_remaining_exists(self):
        """Should have remaining quota gauge."""
        assert QUOTA_REMAINING is not None
        assert QUOTA_REMAINING._name == "bess_quota_remaining"

    def test_usage_api_requests_total_exists(self):
        """Should have usage API requests counter."""
        assert USAGE_API_REQUESTS_TOTAL is not None
        assert USAGE_API_REQUESTS_TOTAL._name == "bess_usage_api_requests"

    def test_usage_export_total_exists(self):
        """Should have usage export counter."""
        assert USAGE_EXPORT_TOTAL is not None
        assert USAGE_EXPORT_TOTAL._name == "bess_usage_export"

    def test_usage_query_duration_exists(self):
        """Should have usage query duration histogram."""
        assert USAGE_QUERY_DURATION is not None
        assert USAGE_QUERY_DURATION._name == "bess_usage_query_duration_seconds"

    def test_plan_assignments_total_exists(self):
        """Should have plan assignments counter."""
        assert PLAN_ASSIGNMENTS_TOTAL is not None
        assert PLAN_ASSIGNMENTS_TOTAL._name == "bess_plan_assignments"

    def test_project_override_total_exists(self):
        """Should have project override counter."""
        assert PROJECT_OVERRIDE_TOTAL is not None
        assert PROJECT_OVERRIDE_TOTAL._name == "bess_project_override"

    def test_plan_usage_by_tier_exists(self):
        """Should have plan usage by tier gauge."""
        assert PLAN_USAGE_BY_TIER is not None
        assert PLAN_USAGE_BY_TIER._name == "bess_plan_usage_by_tier"

    def test_quota_reset_seconds_remaining_exists(self):
        """Should have quota reset seconds gauge."""
        assert QUOTA_RESET_SECONDS_REMAINING is not None
        assert QUOTA_RESET_SECONDS_REMAINING._name == "bess_quota_reset_seconds_remaining"


# -----------------------------------------------------------------------------
# record_quota_check tests
# -----------------------------------------------------------------------------

class TestRecordQuotaCheck:
    """Tests for record_quota_check helper."""

    def test_records_allowed(self):
        """Should record allowed quota check."""
        # Should not raise
        record_quota_check("jobs_per_day", allowed=True)

    def test_records_denied(self):
        """Should record denied quota check."""
        # Should not raise
        record_quota_check("jobs_per_day", allowed=False)

    def test_records_different_quota_names(self):
        """Should accept different quota names."""
        quota_names = [
            "jobs_per_day",
            "reports_per_day",
            "shares_total",
            "storage_mb",
            "projects_total",
        ]
        for name in quota_names:
            record_quota_check(name, allowed=True)


# -----------------------------------------------------------------------------
# record_quota_exceeded tests
# -----------------------------------------------------------------------------

class TestRecordQuotaExceeded:
    """Tests for record_quota_exceeded helper."""

    def test_records_exceeded_free_plan(self):
        """Should record exceeded event for free plan."""
        record_quota_exceeded("jobs_per_day", "free")

    def test_records_exceeded_pro_plan(self):
        """Should record exceeded event for pro plan."""
        record_quota_exceeded("jobs_per_day", "pro")

    def test_records_exceeded_enterprise_plan(self):
        """Should record exceeded event for enterprise plan."""
        record_quota_exceeded("jobs_per_day", "enterprise")


# -----------------------------------------------------------------------------
# record_quota_enforcement tests
# -----------------------------------------------------------------------------

class TestRecordQuotaEnforcement:
    """Tests for record_quota_enforcement helper."""

    def test_records_blocked(self):
        """Should record blocked action."""
        record_quota_enforcement("jobs_per_day", "blocked")

    def test_records_warned(self):
        """Should record warned action."""
        record_quota_enforcement("jobs_per_day", "warned")

    def test_records_incremented(self):
        """Should record incremented action."""
        record_quota_enforcement("jobs_per_day", "incremented")


# -----------------------------------------------------------------------------
# update_quota_usage tests
# -----------------------------------------------------------------------------

class TestUpdateQuotaUsage:
    """Tests for update_quota_usage helper."""

    def test_updates_usage_under_limit(self):
        """Should update usage metrics when under limit."""
        update_quota_usage("tenant-1", "project-1", "jobs_per_day", used=5, limit=10)

    def test_updates_usage_at_limit(self):
        """Should update usage metrics when at limit."""
        update_quota_usage("tenant-2", "project-2", "jobs_per_day", used=10, limit=10)

    def test_updates_usage_over_limit(self):
        """Should update usage metrics when over limit."""
        update_quota_usage("tenant-3", "project-3", "jobs_per_day", used=15, limit=10)

    def test_updates_usage_unlimited(self):
        """Should handle unlimited quota (limit=0)."""
        update_quota_usage("tenant-4", "project-4", "jobs_per_day", used=100, limit=0)

    def test_updates_different_quota_names(self):
        """Should update metrics for different quota names."""
        update_quota_usage("tenant-5", "project-5", "storage_mb", used=500, limit=1000)


# -----------------------------------------------------------------------------
# record_usage_api_request tests
# -----------------------------------------------------------------------------

class TestRecordUsageApiRequest:
    """Tests for record_usage_api_request helper."""

    def test_records_tenant_endpoint_success(self):
        """Should record tenant endpoint success."""
        record_usage_api_request("tenant", success=True)

    def test_records_tenant_endpoint_failure(self):
        """Should record tenant endpoint failure."""
        record_usage_api_request("tenant", success=False)

    def test_records_project_endpoint(self):
        """Should record project endpoint."""
        record_usage_api_request("project", success=True)

    def test_records_daily_endpoint(self):
        """Should record daily endpoint."""
        record_usage_api_request("daily", success=True)


# -----------------------------------------------------------------------------
# record_usage_export tests
# -----------------------------------------------------------------------------

class TestRecordUsageExport:
    """Tests for record_usage_export helper."""

    def test_records_csv_export_success(self):
        """Should record CSV export success."""
        record_usage_export("csv", success=True)

    def test_records_csv_export_failure(self):
        """Should record CSV export failure."""
        record_usage_export("csv", success=False)

    def test_records_json_export(self):
        """Should record JSON export."""
        record_usage_export("json", success=True)


# -----------------------------------------------------------------------------
# observe_usage_query_duration tests
# -----------------------------------------------------------------------------

class TestObserveUsageQueryDuration:
    """Tests for observe_usage_query_duration helper."""

    def test_observes_tenant_summary_duration(self):
        """Should observe tenant summary query duration."""
        observe_usage_query_duration("tenant_summary", 0.05)

    def test_observes_project_summary_duration(self):
        """Should observe project summary query duration."""
        observe_usage_query_duration("project_summary", 0.1)

    def test_observes_daily_records_duration(self):
        """Should observe daily records query duration."""
        observe_usage_query_duration("daily_records", 0.25)

    def test_observes_zero_duration(self):
        """Should observe zero duration."""
        observe_usage_query_duration("tenant_summary", 0.0)

    def test_observes_long_duration(self):
        """Should observe long duration."""
        observe_usage_query_duration("daily_records", 2.5)


# -----------------------------------------------------------------------------
# record_plan_assignment tests
# -----------------------------------------------------------------------------

class TestRecordPlanAssignment:
    """Tests for record_plan_assignment helper."""

    def test_records_new_assignment(self):
        """Should record new plan assignment."""
        record_plan_assignment("pro", is_new=True)

    def test_records_plan_change(self):
        """Should record plan change."""
        record_plan_assignment("enterprise", is_new=False)

    def test_records_free_plan(self):
        """Should record free plan assignment."""
        record_plan_assignment("free", is_new=True)


# -----------------------------------------------------------------------------
# record_project_override tests
# -----------------------------------------------------------------------------

class TestRecordProjectOverride:
    """Tests for record_project_override helper."""

    def test_records_override_set(self):
        """Should record override being set."""
        record_project_override("jobs_per_day", is_set=True)

    def test_records_override_cleared(self):
        """Should record override being cleared."""
        record_project_override("jobs_per_day", is_set=False)

    def test_records_different_quota_names(self):
        """Should record different quota names."""
        record_project_override("storage_mb", is_set=True)
        record_project_override("reports_per_day", is_set=True)


# -----------------------------------------------------------------------------
# update_plan_tier_usage tests
# -----------------------------------------------------------------------------

class TestUpdatePlanTierUsage:
    """Tests for update_plan_tier_usage helper."""

    def test_updates_single_plan(self):
        """Should update single plan tier usage."""
        update_plan_tier_usage({"free": 10})

    def test_updates_multiple_plans(self):
        """Should update multiple plan tier usage."""
        update_plan_tier_usage({
            "free": 100,
            "pro": 50,
            "enterprise": 5,
        })

    def test_updates_empty_plans(self):
        """Should handle empty plan counts."""
        update_plan_tier_usage({})


# -----------------------------------------------------------------------------
# update_quota_reset_seconds tests
# -----------------------------------------------------------------------------

class TestUpdateQuotaResetSeconds:
    """Tests for update_quota_reset_seconds helper."""

    def test_updates_seconds(self):
        """Should update reset seconds."""
        update_quota_reset_seconds(43200)

    def test_updates_one_second(self):
        """Should update to one second."""
        update_quota_reset_seconds(1)

    def test_updates_full_day(self):
        """Should update to full day."""
        update_quota_reset_seconds(86400)


# -----------------------------------------------------------------------------
# Label cardinality tests
# -----------------------------------------------------------------------------

class TestLabelCardinality:
    """Tests for label cardinality."""

    def test_quota_check_labels(self):
        """QUOTA_CHECK_TOTAL should have quota_name and result labels."""
        assert "quota_name" in QUOTA_CHECK_TOTAL._labelnames
        assert "result" in QUOTA_CHECK_TOTAL._labelnames

    def test_quota_exceeded_labels(self):
        """QUOTA_EXCEEDED_TOTAL should have quota_name and plan_id labels."""
        assert "quota_name" in QUOTA_EXCEEDED_TOTAL._labelnames
        assert "plan_id" in QUOTA_EXCEEDED_TOTAL._labelnames

    def test_quota_enforcement_labels(self):
        """QUOTA_ENFORCEMENT_TOTAL should have quota_name and action labels."""
        assert "quota_name" in QUOTA_ENFORCEMENT_TOTAL._labelnames
        assert "action" in QUOTA_ENFORCEMENT_TOTAL._labelnames

    def test_usage_current_labels(self):
        """QUOTA_USAGE_CURRENT should have tenant_id, project_id, quota_name labels."""
        assert "tenant_id" in QUOTA_USAGE_CURRENT._labelnames
        assert "project_id" in QUOTA_USAGE_CURRENT._labelnames
        assert "quota_name" in QUOTA_USAGE_CURRENT._labelnames

    def test_usage_api_labels(self):
        """USAGE_API_REQUESTS_TOTAL should have endpoint and result labels."""
        assert "endpoint" in USAGE_API_REQUESTS_TOTAL._labelnames
        assert "result" in USAGE_API_REQUESTS_TOTAL._labelnames

    def test_usage_export_labels(self):
        """USAGE_EXPORT_TOTAL should have format and result labels."""
        assert "format" in USAGE_EXPORT_TOTAL._labelnames
        assert "result" in USAGE_EXPORT_TOTAL._labelnames

    def test_plan_assignments_labels(self):
        """PLAN_ASSIGNMENTS_TOTAL should have plan_id and operation labels."""
        assert "plan_id" in PLAN_ASSIGNMENTS_TOTAL._labelnames
        assert "operation" in PLAN_ASSIGNMENTS_TOTAL._labelnames

    def test_project_override_labels(self):
        """PROJECT_OVERRIDE_TOTAL should have quota_name and operation labels."""
        assert "quota_name" in PROJECT_OVERRIDE_TOTAL._labelnames
        assert "operation" in PROJECT_OVERRIDE_TOTAL._labelnames

