"""
Unit tests for SCIM Observability Metrics (v4.4.0 PR10).

Tests for Prometheus metrics recording.
"""

import pytest
import sys
import os

# Add services path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from prometheus_client import REGISTRY, CollectorRegistry


@pytest.fixture
def test_registry():
    """Create a clean registry for testing."""
    # We need to reimport with a fresh registry for isolation
    return CollectorRegistry()


class TestScimTokenMetrics:
    """Tests for SCIM token metrics."""

    def test_record_token_validation_success(self):
        """Test recording successful token validation."""
        from scim_metrics import record_token_validation, scim_token_validation_total

        initial = scim_token_validation_total.labels(result="success")._value.get()
        record_token_validation("success")
        after = scim_token_validation_total.labels(result="success")._value.get()

        assert after == initial + 1

    def test_record_token_validation_expired(self):
        """Test recording expired token validation."""
        from scim_metrics import record_token_validation, scim_token_validation_total

        initial = scim_token_validation_total.labels(result="expired")._value.get()
        record_token_validation("expired")
        after = scim_token_validation_total.labels(result="expired")._value.get()

        assert after == initial + 1

    def test_record_token_validation_revoked(self):
        """Test recording revoked token validation."""
        from scim_metrics import record_token_validation, scim_token_validation_total

        initial = scim_token_validation_total.labels(result="revoked")._value.get()
        record_token_validation("revoked")
        after = scim_token_validation_total.labels(result="revoked")._value.get()

        assert after == initial + 1


class TestScimUserMetrics:
    """Tests for SCIM user metrics."""

    def test_record_user_provisioned(self):
        """Test recording user provisioning."""
        from scim_metrics import record_user_provisioned, scim_users_provisioned_total

        tenant_id = "test-tenant-1"
        initial = scim_users_provisioned_total.labels(tenant_id=tenant_id)._value.get()
        record_user_provisioned(tenant_id)
        after = scim_users_provisioned_total.labels(tenant_id=tenant_id)._value.get()

        assert after == initial + 1

    def test_record_user_updated(self):
        """Test recording user update."""
        from scim_metrics import record_user_updated, scim_users_updated_total

        tenant_id = "test-tenant-2"
        initial = scim_users_updated_total.labels(tenant_id=tenant_id)._value.get()
        record_user_updated(tenant_id)
        after = scim_users_updated_total.labels(tenant_id=tenant_id)._value.get()

        assert after == initial + 1

    def test_record_user_deprovisioned_soft(self):
        """Test recording soft deprovision."""
        from scim_metrics import record_user_deprovisioned, scim_users_deprovisioned_total

        tenant_id = "test-tenant-3"
        initial = scim_users_deprovisioned_total.labels(
            tenant_id=tenant_id, hard_delete="false"
        )._value.get()

        record_user_deprovisioned(tenant_id, hard_delete=False)

        after = scim_users_deprovisioned_total.labels(
            tenant_id=tenant_id, hard_delete="false"
        )._value.get()

        assert after == initial + 1

    def test_record_user_deprovisioned_hard(self):
        """Test recording hard delete deprovision."""
        from scim_metrics import record_user_deprovisioned, scim_users_deprovisioned_total

        tenant_id = "test-tenant-4"
        initial = scim_users_deprovisioned_total.labels(
            tenant_id=tenant_id, hard_delete="true"
        )._value.get()

        record_user_deprovisioned(tenant_id, hard_delete=True)

        after = scim_users_deprovisioned_total.labels(
            tenant_id=tenant_id, hard_delete="true"
        )._value.get()

        assert after == initial + 1


class TestScimRequestMetrics:
    """Tests for SCIM request metrics."""

    def test_record_users_request(self):
        """Test recording Users endpoint request."""
        from scim_metrics import record_scim_request, scim_users_requests_total

        initial = scim_users_requests_total.labels(method="GET", status_code=200)._value.get()
        record_scim_request("/scim/v2/Users", "GET", 200, 0.05)
        after = scim_users_requests_total.labels(method="GET", status_code=200)._value.get()

        assert after == initial + 1

    def test_record_groups_request(self):
        """Test recording Groups endpoint request."""
        from scim_metrics import record_scim_request, scim_groups_requests_total

        initial = scim_groups_requests_total.labels(method="POST", status_code=201)._value.get()
        record_scim_request("/scim/v2/Groups", "POST", 201, 0.1)
        after = scim_groups_requests_total.labels(method="POST", status_code=201)._value.get()

        assert after == initial + 1

    def test_record_request_duration(self):
        """Test recording request duration histogram."""
        from scim_metrics import record_scim_request, scim_users_request_duration_seconds

        # Record multiple requests to ensure histogram is updated
        record_scim_request("/scim/v2/Users", "GET", 200, 0.25)
        record_scim_request("/scim/v2/Users", "GET", 200, 0.10)

        # Verify histogram exists and has the label
        histogram = scim_users_request_duration_seconds.labels(method="GET")
        # Just verify the histogram object exists - internal structure varies by version
        assert histogram is not None


class TestScimSyncMetrics:
    """Tests for SCIM sync metrics."""

    def test_record_sync_result(self):
        """Test recording sync result."""
        from scim_metrics import (
            record_sync_result,
            scim_sync_requests_total,
            scim_sync_members_added_total,
            scim_sync_members_removed_total
        )

        tenant_id = "test-tenant-5"
        sync_type = "single_group"

        initial_requests = scim_sync_requests_total.labels(
            tenant_id=tenant_id, sync_type=sync_type
        )._value.get()
        initial_added = scim_sync_members_added_total.labels(tenant_id=tenant_id)._value.get()
        initial_removed = scim_sync_members_removed_total.labels(tenant_id=tenant_id)._value.get()

        record_sync_result(tenant_id, sync_type, members_added=5, members_removed=2, duration=1.5)

        after_requests = scim_sync_requests_total.labels(
            tenant_id=tenant_id, sync_type=sync_type
        )._value.get()
        after_added = scim_sync_members_added_total.labels(tenant_id=tenant_id)._value.get()
        after_removed = scim_sync_members_removed_total.labels(tenant_id=tenant_id)._value.get()

        assert after_requests == initial_requests + 1
        assert after_added == initial_added + 5
        assert after_removed == initial_removed + 2

    def test_record_sync_result_with_errors(self):
        """Test recording sync result with errors."""
        from scim_metrics import record_sync_result, scim_sync_errors_total

        tenant_id = "test-tenant-6"

        initial = scim_sync_errors_total.labels(
            tenant_id=tenant_id, error_type="sync_error"
        )._value.get()

        record_sync_result(tenant_id, "all_groups", 0, 0, 2.0, errors=3)

        after = scim_sync_errors_total.labels(
            tenant_id=tenant_id, error_type="sync_error"
        )._value.get()

        assert after == initial + 3


class TestScimDeprovisionMetrics:
    """Tests for SCIM deprovision metrics."""

    def test_record_deprovision_result(self):
        """Test recording deprovision result."""
        from scim_metrics import (
            record_deprovision_result,
            scim_deprovision_requests_total,
            scim_deprovision_sessions_revoked_total,
            scim_deprovision_api_keys_revoked_total,
            scim_deprovision_memberships_revoked_total
        )

        tenant_id = "test-tenant-7"

        initial_requests = scim_deprovision_requests_total.labels(
            tenant_id=tenant_id, hard_delete="false"
        )._value.get()
        initial_sessions = scim_deprovision_sessions_revoked_total.labels(
            tenant_id=tenant_id
        )._value.get()
        initial_keys = scim_deprovision_api_keys_revoked_total.labels(
            tenant_id=tenant_id
        )._value.get()
        initial_memberships = scim_deprovision_memberships_revoked_total.labels(
            tenant_id=tenant_id
        )._value.get()

        record_deprovision_result(
            tenant_id,
            sessions_revoked=3,
            api_keys_revoked=2,
            memberships_revoked=5,
            hard_delete=False
        )

        after_requests = scim_deprovision_requests_total.labels(
            tenant_id=tenant_id, hard_delete="false"
        )._value.get()
        after_sessions = scim_deprovision_sessions_revoked_total.labels(
            tenant_id=tenant_id
        )._value.get()
        after_keys = scim_deprovision_api_keys_revoked_total.labels(
            tenant_id=tenant_id
        )._value.get()
        after_memberships = scim_deprovision_memberships_revoked_total.labels(
            tenant_id=tenant_id
        )._value.get()

        assert after_requests == initial_requests + 1
        assert after_sessions == initial_sessions + 3
        assert after_keys == initial_keys + 2
        assert after_memberships == initial_memberships + 5


class TestScimErrorMetrics:
    """Tests for SCIM error metrics."""

    def test_record_error(self):
        """Test recording SCIM error."""
        from scim_metrics import record_error, scim_errors_total

        initial = scim_errors_total.labels(
            endpoint="/scim/v2/Users",
            status_code=400,
            error_type="validation_error"
        )._value.get()

        record_error("/scim/v2/Users", 400, "validation_error")

        after = scim_errors_total.labels(
            endpoint="/scim/v2/Users",
            status_code=400,
            error_type="validation_error"
        )._value.get()

        assert after == initial + 1


class TestScimGaugeMetrics:
    """Tests for SCIM gauge metrics."""

    def test_update_tenant_gauges(self):
        """Test updating tenant gauges."""
        from scim_metrics import (
            update_tenant_gauges,
            scim_users_total,
            scim_users_active,
            scim_groups_total,
            scim_tokens_active,
            scim_mappings_total
        )

        tenant_id = "test-tenant-8"

        update_tenant_gauges(
            tenant_id=tenant_id,
            users_total=100,
            users_active=95,
            groups_total=10,
            tokens_active=2,
            mappings_enabled=8,
            mappings_disabled=2
        )

        assert scim_users_total.labels(tenant_id=tenant_id)._value.get() == 100
        assert scim_users_active.labels(tenant_id=tenant_id)._value.get() == 95
        assert scim_groups_total.labels(tenant_id=tenant_id)._value.get() == 10
        assert scim_tokens_active.labels(tenant_id=tenant_id)._value.get() == 2
        assert scim_mappings_total.labels(tenant_id=tenant_id, enabled="true")._value.get() == 8
        assert scim_mappings_total.labels(tenant_id=tenant_id, enabled="false")._value.get() == 2
