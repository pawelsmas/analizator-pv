"""
Unit tests for retention policy merge logic (v4.3.0 PR2).

Tests:
- merge_policies() function
- Priority: project > tenant > system default
- Handling of -1 (inherit) values
- Handling of 0 (indefinite) values
- Validation logic
"""

import os
import sys
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from retention_policy_helper import (
    RetentionPolicy,
    ResourceCategory,
    merge_policies,
    validate_policy,
    validate_policy_strict,
    compute_cutoff_date,
    is_resource_expired,
    format_retention_period,
    summarize_policy,
    PolicyValidationError,
    DEFAULT_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
)


class TestRetentionPolicyModel:
    """Tests for RetentionPolicy model."""

    def test_create_empty_policy(self):
        """Test creating policy with no values."""
        policy = RetentionPolicy()
        assert policy.runs_days is None
        assert policy.jobs_days is None
        assert policy.reports_days is None
        assert policy.audit_logs_days is None
        assert policy.exports_days is None

    def test_create_policy_with_values(self):
        """Test creating policy with specific values."""
        policy = RetentionPolicy(
            runs_days=365,
            jobs_days=90,
            audit_logs_days=730,
        )
        assert policy.runs_days == 365
        assert policy.jobs_days == 90
        assert policy.audit_logs_days == 730
        assert policy.reports_days is None
        assert policy.exports_days is None

    def test_to_dict_excludes_none(self):
        """Test to_dict() excludes None values."""
        policy = RetentionPolicy(runs_days=365, jobs_days=90)
        d = policy.to_dict()
        assert d == {"runs_days": 365, "jobs_days": 90}
        assert "reports_days" not in d

    def test_from_dict(self):
        """Test creating policy from dictionary."""
        data = {"runs_days": 180, "exports_days": 30}
        policy = RetentionPolicy.from_dict(data)
        assert policy.runs_days == 180
        assert policy.exports_days == 30
        assert policy.jobs_days is None

    def test_get_category_days(self):
        """Test getting days for a specific category."""
        policy = RetentionPolicy(runs_days=365, jobs_days=90)
        assert policy.get_category_days(ResourceCategory.RUNS) == 365
        assert policy.get_category_days(ResourceCategory.JOBS) == 90
        assert policy.get_category_days(ResourceCategory.REPORTS) is None

    def test_validation_rejects_invalid_days(self):
        """Test that negative values (except -1) are rejected."""
        with pytest.raises(ValueError, match="must be >= -1"):
            RetentionPolicy(runs_days=-5)

    def test_validation_accepts_inherit_value(self):
        """Test that -1 (inherit) is accepted."""
        policy = RetentionPolicy(runs_days=-1)
        assert policy.runs_days == -1

    def test_validation_accepts_zero_indefinite(self):
        """Test that 0 (indefinite) is accepted."""
        policy = RetentionPolicy(runs_days=0)
        assert policy.runs_days == 0


class TestMergePolicies:
    """Tests for merge_policies() function."""

    def test_merge_with_no_policies(self):
        """Test merge with both policies None - returns system defaults."""
        result = merge_policies(None, None)
        assert result.runs_days == DEFAULT_RETENTION_DAYS[ResourceCategory.RUNS]
        assert result.jobs_days == DEFAULT_RETENTION_DAYS[ResourceCategory.JOBS]
        assert result.audit_logs_days == DEFAULT_RETENTION_DAYS[ResourceCategory.AUDIT_LOGS]

    def test_tenant_overrides_system_default(self):
        """Test tenant policy overrides system default."""
        tenant = RetentionPolicy(runs_days=180)
        result = merge_policies(tenant, None)
        assert result.runs_days == 180
        # Others should be system defaults
        assert result.jobs_days == DEFAULT_RETENTION_DAYS[ResourceCategory.JOBS]

    def test_project_overrides_tenant(self):
        """Test project policy overrides tenant policy."""
        tenant = RetentionPolicy(runs_days=365)
        project = RetentionPolicy(runs_days=90)
        result = merge_policies(tenant, project)
        assert result.runs_days == 90

    def test_project_inherits_from_tenant(self):
        """Test project with -1 inherits from tenant."""
        tenant = RetentionPolicy(runs_days=365, jobs_days=90)
        project = RetentionPolicy(runs_days=-1, jobs_days=30)
        result = merge_policies(tenant, project)
        assert result.runs_days == 365  # Inherited from tenant
        assert result.jobs_days == 30   # Project override

    def test_project_inherits_from_system_when_tenant_none(self):
        """Test inheritance chain: project -> tenant (none) -> system."""
        project = RetentionPolicy(runs_days=-1)
        result = merge_policies(None, project)
        assert result.runs_days == DEFAULT_RETENTION_DAYS[ResourceCategory.RUNS]

    def test_indefinite_retention_preserved(self):
        """Test that 0 (indefinite) is preserved in merge."""
        tenant = RetentionPolicy(runs_days=365)
        project = RetentionPolicy(runs_days=0)  # Never delete
        result = merge_policies(tenant, project)
        assert result.runs_days == 0

    def test_partial_override(self):
        """Test partial override - only some fields specified."""
        tenant = RetentionPolicy(
            runs_days=365,
            jobs_days=180,
            reports_days=365,
        )
        project = RetentionPolicy(
            jobs_days=90,  # Only override jobs
        )
        result = merge_policies(tenant, project)
        assert result.runs_days == 365   # From tenant
        assert result.jobs_days == 90    # From project
        assert result.reports_days == 365  # From tenant

    def test_all_categories_merged(self):
        """Test that all categories are present in result."""
        result = merge_policies(None, None)
        assert result.runs_days is not None
        assert result.jobs_days is not None
        assert result.reports_days is not None
        assert result.audit_logs_days is not None
        assert result.exports_days is not None


class TestValidatePolicy:
    """Tests for validate_policy() function."""

    def test_valid_policy_no_errors(self):
        """Test valid policy returns empty errors list."""
        policy = RetentionPolicy(
            runs_days=365,
            jobs_days=90,
            audit_logs_days=730,
        )
        errors = validate_policy(policy)
        assert errors == []

    def test_below_minimum_rejected(self):
        """Test values below minimum are rejected."""
        policy = RetentionPolicy(runs_days=1)  # Min is 7
        errors = validate_policy(policy)
        assert len(errors) == 1
        assert "below minimum" in errors[0]

    def test_above_maximum_rejected(self):
        """Test values above maximum are rejected."""
        policy = RetentionPolicy(runs_days=5000)  # Max is 3650
        errors = validate_policy(policy)
        assert len(errors) == 1
        assert "exceeds maximum" in errors[0]

    def test_audit_logs_minimum_compliance(self):
        """Test audit logs have minimum compliance requirement."""
        policy = RetentionPolicy(audit_logs_days=30)  # Min is 90
        errors = validate_policy(policy)
        assert len(errors) == 1
        assert "audit_logs_days" in errors[0]

    def test_inherit_value_skipped(self):
        """Test -1 (inherit) value is not validated."""
        policy = RetentionPolicy(runs_days=-1)
        errors = validate_policy(policy)
        assert errors == []

    def test_indefinite_always_valid(self):
        """Test 0 (indefinite) is always valid."""
        policy = RetentionPolicy(runs_days=0, audit_logs_days=0)
        errors = validate_policy(policy)
        assert errors == []

    def test_validate_strict_raises(self):
        """Test validate_policy_strict raises on errors."""
        policy = RetentionPolicy(runs_days=1)
        with pytest.raises(PolicyValidationError) as exc_info:
            validate_policy_strict(policy)
        assert "below minimum" in str(exc_info.value)

    def test_multiple_errors_collected(self):
        """Test multiple errors are collected."""
        policy = RetentionPolicy(
            runs_days=1,        # Below min
            jobs_days=5000,     # Above max
            audit_logs_days=30, # Below compliance min
        )
        errors = validate_policy(policy)
        assert len(errors) == 3


class TestComputeCutoffDate:
    """Tests for compute_cutoff_date() function."""

    def test_compute_cutoff_basic(self):
        """Test basic cutoff date computation."""
        policy = RetentionPolicy(runs_days=30)
        ref_date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        cutoff = compute_cutoff_date(ResourceCategory.RUNS, policy, ref_date)
        expected = datetime(2024, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        assert cutoff == expected

    def test_indefinite_returns_none(self):
        """Test indefinite retention returns None cutoff."""
        policy = RetentionPolicy(runs_days=0)
        cutoff = compute_cutoff_date(ResourceCategory.RUNS, policy)
        assert cutoff is None

    def test_uses_default_when_not_specified(self):
        """Test uses system default when not specified in policy."""
        policy = RetentionPolicy()  # No runs_days
        ref_date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        cutoff = compute_cutoff_date(ResourceCategory.RUNS, policy, ref_date)
        expected_days = DEFAULT_RETENTION_DAYS[ResourceCategory.RUNS]
        expected = ref_date - timedelta(days=expected_days)
        assert cutoff == expected

    def test_uses_current_time_when_no_reference(self):
        """Test uses current time when no reference provided."""
        policy = RetentionPolicy(runs_days=30)
        cutoff = compute_cutoff_date(ResourceCategory.RUNS, policy)
        # Should be roughly 30 days ago
        expected_approx = datetime.now(timezone.utc) - timedelta(days=30)
        assert abs((cutoff - expected_approx).total_seconds()) < 2


class TestIsResourceExpired:
    """Tests for is_resource_expired() function."""

    def test_old_resource_is_expired(self):
        """Test resource older than retention is expired."""
        policy = RetentionPolicy(runs_days=30)
        created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ref = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert is_resource_expired(created, ResourceCategory.RUNS, policy, ref) is True

    def test_recent_resource_not_expired(self):
        """Test resource within retention is not expired."""
        policy = RetentionPolicy(runs_days=30)
        created = datetime(2024, 5, 15, tzinfo=timezone.utc)
        ref = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert is_resource_expired(created, ResourceCategory.RUNS, policy, ref) is False

    def test_indefinite_never_expired(self):
        """Test indefinite retention never expires."""
        policy = RetentionPolicy(runs_days=0)
        created = datetime(2000, 1, 1, tzinfo=timezone.utc)  # Very old
        assert is_resource_expired(created, ResourceCategory.RUNS, policy) is False

    def test_handles_naive_datetime(self):
        """Test handles naive datetime (assumes UTC)."""
        policy = RetentionPolicy(runs_days=30)
        created = datetime(2024, 1, 1)  # Naive
        ref = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert is_resource_expired(created, ResourceCategory.RUNS, policy, ref) is True


class TestFormatRetentionPeriod:
    """Tests for format_retention_period() function."""

    def test_format_indefinite(self):
        """Test formatting 0 as Indefinite."""
        assert format_retention_period(0) == "Indefinite"

    def test_format_one_day(self):
        """Test formatting 1 day."""
        assert format_retention_period(1) == "1 day"

    def test_format_days(self):
        """Test formatting days under 30."""
        assert format_retention_period(7) == "7 days"
        assert format_retention_period(14) == "14 days"

    def test_format_months(self):
        """Test formatting as months."""
        assert format_retention_period(30) == "1 month"
        assert format_retention_period(90) == "3 months"
        assert format_retention_period(180) == "6 months"

    def test_format_years(self):
        """Test formatting as years."""
        assert format_retention_period(365) == "1 year"
        assert format_retention_period(730) == "2 years"


class TestSummarizePolicy:
    """Tests for summarize_policy() function."""

    def test_summarize_with_values(self):
        """Test summarizing policy with specified values."""
        policy = RetentionPolicy(
            runs_days=365,
            jobs_days=90,
            audit_logs_days=730,
        )
        summary = summarize_policy(policy)
        assert summary["runs"] == "1 year"
        assert summary["jobs"] == "3 months"
        assert summary["audit_logs"] == "2 years"

    def test_summarize_uses_defaults(self):
        """Test summarizing uses defaults for unspecified."""
        policy = RetentionPolicy()
        summary = summarize_policy(policy)
        # Should have all categories with default values formatted
        assert "runs" in summary
        assert "jobs" in summary
        assert "reports" in summary
        assert "audit_logs" in summary
        assert "exports" in summary

    def test_summarize_indefinite(self):
        """Test summarizing indefinite retention."""
        policy = RetentionPolicy(runs_days=0)
        summary = summarize_policy(policy)
        assert summary["runs"] == "Indefinite"
