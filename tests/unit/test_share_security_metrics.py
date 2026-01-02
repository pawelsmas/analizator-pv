"""
Unit tests for share security metrics (v3.8.0 PR6).

Tests for auth_metrics.py v3.8.0 share security additions:
- SHARE_V2_CREATED_TOTAL
- SHARE_ACCESS_DENIED_TOTAL
- SHARE_TOKEN_ROTATION_TOTAL
- SHARE_REVOKE_ALL_TOTAL
- SHARE_RETENTION_PURGE_TOTAL
- SHARE_PASSWORD_ATTEMPTS_TOTAL
- SHARE_ACCESS_COUNT_EXCEEDED_TOTAL
- SHARE_ACCESS_LOG_ENTRIES_TOTAL
- SHARE_STATS_QUERIES_TOTAL
"""

import os
import sys

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from observability.auth_metrics import (
    # Counters
    SHARE_V2_CREATED_TOTAL,
    SHARE_ACCESS_DENIED_TOTAL,
    SHARE_TOKEN_ROTATION_TOTAL,
    SHARE_REVOKE_ALL_TOTAL,
    SHARE_RETENTION_PURGE_TOTAL,
    SHARE_RETENTION_PURGED_ITEMS_TOTAL,
    SHARE_PASSWORD_ATTEMPTS_TOTAL,
    SHARE_ACCESS_COUNT_EXCEEDED_TOTAL,
    SHARE_ACCESS_LOG_ENTRIES_TOTAL,
    SHARE_STATS_QUERIES_TOTAL,
    # Helper functions
    record_share_v2_created,
    record_share_access_denied,
    record_share_token_rotation,
    record_share_revoke_all,
    record_share_retention_purge,
    record_share_password_attempt,
    record_share_access_count_exceeded,
    record_share_access_log_entry,
    record_share_stats_query,
)


class TestShareV2CreatedMetric:
    """Tests for SHARE_V2_CREATED_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_V2_CREATED_TOTAL is not None
        # Verify it has the expected label names
        labels = SHARE_V2_CREATED_TOTAL._labelnames
        assert "resource_type" in labels
        assert "has_password" in labels
        assert "single_use" in labels
        assert "has_max_access" in labels

    def test_record_share_v2_created_basic(self):
        """Test recording basic share creation (no security features)."""
        before = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="run",
            has_password="false",
            single_use="false",
            has_max_access="false",
        )._value.get()

        record_share_v2_created(
            resource_type="run",
            has_password=False,
            single_use=False,
            has_max_access=False,
        )

        after = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="run",
            has_password="false",
            single_use="false",
            has_max_access="false",
        )._value.get()

        assert after == before + 1

    def test_record_share_v2_created_with_password(self):
        """Test recording password-protected share."""
        before = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="run",
            has_password="true",
            single_use="false",
            has_max_access="false",
        )._value.get()

        record_share_v2_created(
            resource_type="run",
            has_password=True,
            single_use=False,
            has_max_access=False,
        )

        after = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="run",
            has_password="true",
            single_use="false",
            has_max_access="false",
        )._value.get()

        assert after == before + 1

    def test_record_share_v2_created_single_use(self):
        """Test recording single-use share."""
        before = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="report",
            has_password="false",
            single_use="true",
            has_max_access="false",
        )._value.get()

        record_share_v2_created(
            resource_type="report",
            has_password=False,
            single_use=True,
            has_max_access=False,
        )

        after = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="report",
            has_password="false",
            single_use="true",
            has_max_access="false",
        )._value.get()

        assert after == before + 1

    def test_record_share_v2_created_with_max_access(self):
        """Test recording share with max access count."""
        before = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="run",
            has_password="false",
            single_use="false",
            has_max_access="true",
        )._value.get()

        record_share_v2_created(
            resource_type="run",
            has_password=False,
            single_use=False,
            has_max_access=True,
        )

        after = SHARE_V2_CREATED_TOTAL.labels(
            resource_type="run",
            has_password="false",
            single_use="false",
            has_max_access="true",
        )._value.get()

        assert after == before + 1


class TestShareAccessDeniedMetric:
    """Tests for SHARE_ACCESS_DENIED_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_ACCESS_DENIED_TOTAL is not None
        labels = SHARE_ACCESS_DENIED_TOTAL._labelnames
        assert "resource_type" in labels
        assert "denial_reason" in labels

    def test_record_password_required(self):
        """Test recording password_required denial."""
        before = SHARE_ACCESS_DENIED_TOTAL.labels(
            resource_type="run",
            denial_reason="password_required",
        )._value.get()

        record_share_access_denied("run", "password_required")

        after = SHARE_ACCESS_DENIED_TOTAL.labels(
            resource_type="run",
            denial_reason="password_required",
        )._value.get()

        assert after == before + 1

    def test_record_invalid_password(self):
        """Test recording invalid_password denial."""
        before = SHARE_ACCESS_DENIED_TOTAL.labels(
            resource_type="run",
            denial_reason="invalid_password",
        )._value.get()

        record_share_access_denied("run", "invalid_password")

        after = SHARE_ACCESS_DENIED_TOTAL.labels(
            resource_type="run",
            denial_reason="invalid_password",
        )._value.get()

        assert after == before + 1

    def test_record_access_limit_exceeded(self):
        """Test recording access_limit_exceeded denial."""
        before = SHARE_ACCESS_DENIED_TOTAL.labels(
            resource_type="report",
            denial_reason="access_limit_exceeded",
        )._value.get()

        record_share_access_denied("report", "access_limit_exceeded")

        after = SHARE_ACCESS_DENIED_TOTAL.labels(
            resource_type="report",
            denial_reason="access_limit_exceeded",
        )._value.get()

        assert after == before + 1


class TestShareTokenRotationMetric:
    """Tests for SHARE_TOKEN_ROTATION_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_TOKEN_ROTATION_TOTAL is not None
        labels = SHARE_TOKEN_ROTATION_TOTAL._labelnames
        assert "result" in labels

    def test_record_rotation_success(self):
        """Test recording successful rotation."""
        before = SHARE_TOKEN_ROTATION_TOTAL.labels(result="success")._value.get()

        record_share_token_rotation(success=True)

        after = SHARE_TOKEN_ROTATION_TOTAL.labels(result="success")._value.get()

        assert after == before + 1

    def test_record_rotation_failure(self):
        """Test recording failed rotation."""
        before = SHARE_TOKEN_ROTATION_TOTAL.labels(result="failure")._value.get()

        record_share_token_rotation(success=False)

        after = SHARE_TOKEN_ROTATION_TOTAL.labels(result="failure")._value.get()

        assert after == before + 1


class TestShareRevokeAllMetric:
    """Tests for SHARE_REVOKE_ALL_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_REVOKE_ALL_TOTAL is not None
        labels = SHARE_REVOKE_ALL_TOTAL._labelnames
        assert "scope" in labels
        assert "result" in labels

    def test_record_revoke_all_project(self):
        """Test recording project-scope revoke all."""
        before = SHARE_REVOKE_ALL_TOTAL.labels(scope="project", result="success")._value.get()

        record_share_revoke_all("project", success=True)

        after = SHARE_REVOKE_ALL_TOTAL.labels(scope="project", result="success")._value.get()

        assert after == before + 1

    def test_record_revoke_all_resource(self):
        """Test recording resource-scope revoke all."""
        before = SHARE_REVOKE_ALL_TOTAL.labels(scope="resource", result="success")._value.get()

        record_share_revoke_all("resource", success=True)

        after = SHARE_REVOKE_ALL_TOTAL.labels(scope="resource", result="success")._value.get()

        assert after == before + 1


class TestShareRetentionPurgeMetric:
    """Tests for SHARE_RETENTION_PURGE_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_RETENTION_PURGE_TOTAL is not None
        labels = SHARE_RETENTION_PURGE_TOTAL._labelnames
        assert "purge_type" in labels
        assert "result" in labels

    def test_record_purge_expired_shares(self):
        """Test recording expired shares purge."""
        before = SHARE_RETENTION_PURGE_TOTAL.labels(
            purge_type="expired_shares",
            result="success",
        )._value.get()

        record_share_retention_purge("expired_shares", success=True, deleted_count=5)

        after = SHARE_RETENTION_PURGE_TOTAL.labels(
            purge_type="expired_shares",
            result="success",
        )._value.get()

        assert after == before + 1

    def test_record_purge_increments_items_count(self):
        """Test that deleted_count is tracked."""
        before = SHARE_RETENTION_PURGED_ITEMS_TOTAL.labels(
            purge_type="revoked_shares",
        )._value.get()

        record_share_retention_purge("revoked_shares", success=True, deleted_count=10)

        after = SHARE_RETENTION_PURGED_ITEMS_TOTAL.labels(
            purge_type="revoked_shares",
        )._value.get()

        assert after == before + 10

    def test_record_purge_access_logs(self):
        """Test recording access logs prune."""
        before = SHARE_RETENTION_PURGE_TOTAL.labels(
            purge_type="access_logs",
            result="success",
        )._value.get()

        record_share_retention_purge("access_logs", success=True, deleted_count=100)

        after = SHARE_RETENTION_PURGE_TOTAL.labels(
            purge_type="access_logs",
            result="success",
        )._value.get()

        assert after == before + 1


class TestSharePasswordAttemptsMetric:
    """Tests for SHARE_PASSWORD_ATTEMPTS_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_PASSWORD_ATTEMPTS_TOTAL is not None
        labels = SHARE_PASSWORD_ATTEMPTS_TOTAL._labelnames
        assert "result" in labels

    def test_record_password_success(self):
        """Test recording successful password attempt."""
        before = SHARE_PASSWORD_ATTEMPTS_TOTAL.labels(result="success")._value.get()

        record_share_password_attempt(success=True)

        after = SHARE_PASSWORD_ATTEMPTS_TOTAL.labels(result="success")._value.get()

        assert after == before + 1

    def test_record_password_failure(self):
        """Test recording failed password attempt."""
        before = SHARE_PASSWORD_ATTEMPTS_TOTAL.labels(result="failure")._value.get()

        record_share_password_attempt(success=False)

        after = SHARE_PASSWORD_ATTEMPTS_TOTAL.labels(result="failure")._value.get()

        assert after == before + 1


class TestShareAccessCountExceededMetric:
    """Tests for SHARE_ACCESS_COUNT_EXCEEDED_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_ACCESS_COUNT_EXCEEDED_TOTAL is not None
        labels = SHARE_ACCESS_COUNT_EXCEEDED_TOTAL._labelnames
        assert "resource_type" in labels

    def test_record_access_count_exceeded(self):
        """Test recording access count exceeded event."""
        before = SHARE_ACCESS_COUNT_EXCEEDED_TOTAL.labels(resource_type="run")._value.get()

        record_share_access_count_exceeded("run")

        after = SHARE_ACCESS_COUNT_EXCEEDED_TOTAL.labels(resource_type="run")._value.get()

        assert after == before + 1


class TestShareAccessLogEntriesMetric:
    """Tests for SHARE_ACCESS_LOG_ENTRIES_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined with correct labels."""
        assert SHARE_ACCESS_LOG_ENTRIES_TOTAL is not None
        labels = SHARE_ACCESS_LOG_ENTRIES_TOTAL._labelnames
        assert "access_result" in labels

    def test_record_log_entry_success(self):
        """Test recording success log entry."""
        before = SHARE_ACCESS_LOG_ENTRIES_TOTAL.labels(access_result="success")._value.get()

        record_share_access_log_entry("success")

        after = SHARE_ACCESS_LOG_ENTRIES_TOTAL.labels(access_result="success")._value.get()

        assert after == before + 1

    def test_record_log_entry_denied(self):
        """Test recording denied log entry."""
        before = SHARE_ACCESS_LOG_ENTRIES_TOTAL.labels(access_result="denied")._value.get()

        record_share_access_log_entry("denied")

        after = SHARE_ACCESS_LOG_ENTRIES_TOTAL.labels(access_result="denied")._value.get()

        assert after == before + 1


class TestShareStatsQueriesMetric:
    """Tests for SHARE_STATS_QUERIES_TOTAL counter."""

    def test_counter_exists(self):
        """Verify counter is defined."""
        assert SHARE_STATS_QUERIES_TOTAL is not None

    def test_record_stats_query(self):
        """Test recording stats query."""
        before = SHARE_STATS_QUERIES_TOTAL._value.get()

        record_share_stats_query()

        after = SHARE_STATS_QUERIES_TOTAL._value.get()

        assert after == before + 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
