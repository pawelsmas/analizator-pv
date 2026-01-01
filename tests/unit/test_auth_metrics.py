"""
Unit tests for auth observability metrics (v3.1.0).

Tests verify:
- Auth metrics are defined correctly
- Helper functions record metrics
- Labels are correct
- v3.1.0: Invite, share, and user admin metrics
"""

import pytest
import sys
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestAuthMetricsDefinitions:
    """Tests for auth metrics definitions."""

    def test_auth_login_counter_exists(self):
        """AUTH_LOGIN_TOTAL counter should be defined."""
        from observability.auth_metrics import AUTH_LOGIN_TOTAL

        assert AUTH_LOGIN_TOTAL is not None
        # prometheus_client stores name without _total suffix for counters
        assert "bess_auth_login" in AUTH_LOGIN_TOTAL._name

    def test_token_validations_counter_exists(self):
        """AUTH_TOKEN_VALIDATIONS_TOTAL counter should be defined."""
        from observability.auth_metrics import AUTH_TOKEN_VALIDATIONS_TOTAL

        assert AUTH_TOKEN_VALIDATIONS_TOTAL is not None
        assert "bess_auth_token_validations" in AUTH_TOKEN_VALIDATIONS_TOTAL._name

    def test_api_key_validations_counter_exists(self):
        """AUTH_API_KEY_VALIDATIONS_TOTAL counter should be defined."""
        from observability.auth_metrics import AUTH_API_KEY_VALIDATIONS_TOTAL

        assert AUTH_API_KEY_VALIDATIONS_TOTAL is not None
        assert "bess_auth_api_key_validations" in AUTH_API_KEY_VALIDATIONS_TOTAL._name

    def test_api_key_operations_counter_exists(self):
        """AUTH_API_KEY_OPERATIONS_TOTAL counter should be defined."""
        from observability.auth_metrics import AUTH_API_KEY_OPERATIONS_TOTAL

        assert AUTH_API_KEY_OPERATIONS_TOTAL is not None
        assert "bess_auth_api_key_operations" in AUTH_API_KEY_OPERATIONS_TOTAL._name

    def test_audit_log_writes_counter_exists(self):
        """AUDIT_LOG_WRITES_TOTAL counter should be defined."""
        from observability.auth_metrics import AUDIT_LOG_WRITES_TOTAL

        assert AUDIT_LOG_WRITES_TOTAL is not None
        assert "bess_audit_log_writes" in AUDIT_LOG_WRITES_TOTAL._name

    def test_auth_requests_counter_exists(self):
        """AUTH_REQUESTS_TOTAL counter should be defined."""
        from observability.auth_metrics import AUTH_REQUESTS_TOTAL

        assert AUTH_REQUESTS_TOTAL is not None
        assert "bess_auth_requests" in AUTH_REQUESTS_TOTAL._name

    def test_rbac_checks_counter_exists(self):
        """RBAC_CHECKS_TOTAL counter should be defined."""
        from observability.auth_metrics import RBAC_CHECKS_TOTAL

        assert RBAC_CHECKS_TOTAL is not None
        assert "bess_rbac_checks" in RBAC_CHECKS_TOTAL._name


class TestAuthMetricsLabels:
    """Tests for auth metrics labels."""

    def test_login_counter_has_result_label(self):
        """AUTH_LOGIN_TOTAL should have result label."""
        from observability.auth_metrics import AUTH_LOGIN_TOTAL

        assert "result" in AUTH_LOGIN_TOTAL._labelnames

    def test_token_validations_has_result_label(self):
        """AUTH_TOKEN_VALIDATIONS_TOTAL should have result label."""
        from observability.auth_metrics import AUTH_TOKEN_VALIDATIONS_TOTAL

        assert "result" in AUTH_TOKEN_VALIDATIONS_TOTAL._labelnames

    def test_api_key_operations_has_operation_label(self):
        """AUTH_API_KEY_OPERATIONS_TOTAL should have operation label."""
        from observability.auth_metrics import AUTH_API_KEY_OPERATIONS_TOTAL

        assert "operation" in AUTH_API_KEY_OPERATIONS_TOTAL._labelnames
        assert "result" in AUTH_API_KEY_OPERATIONS_TOTAL._labelnames

    def test_audit_log_writes_has_action_label(self):
        """AUDIT_LOG_WRITES_TOTAL should have action label."""
        from observability.auth_metrics import AUDIT_LOG_WRITES_TOTAL

        assert "action" in AUDIT_LOG_WRITES_TOTAL._labelnames

    def test_auth_requests_has_method_and_role_labels(self):
        """AUTH_REQUESTS_TOTAL should have auth_method and role labels."""
        from observability.auth_metrics import AUTH_REQUESTS_TOTAL

        assert "auth_method" in AUTH_REQUESTS_TOTAL._labelnames
        assert "role" in AUTH_REQUESTS_TOTAL._labelnames

    def test_rbac_checks_has_required_role_label(self):
        """RBAC_CHECKS_TOTAL should have required_role and result labels."""
        from observability.auth_metrics import RBAC_CHECKS_TOTAL

        assert "required_role" in RBAC_CHECKS_TOTAL._labelnames
        assert "result" in RBAC_CHECKS_TOTAL._labelnames


class TestAuthMetricsHelpers:
    """Tests for auth metrics helper functions."""

    def test_record_login_success(self):
        """record_login should increment success counter."""
        from observability.auth_metrics import record_login, AUTH_LOGIN_TOTAL

        # Get initial value
        initial = AUTH_LOGIN_TOTAL.labels(result="success")._value.get()

        record_login(success=True)

        # Should increment
        assert AUTH_LOGIN_TOTAL.labels(result="success")._value.get() == initial + 1

    def test_record_login_failure(self):
        """record_login should increment failure counter."""
        from observability.auth_metrics import record_login, AUTH_LOGIN_TOTAL

        initial = AUTH_LOGIN_TOTAL.labels(result="failure")._value.get()

        record_login(success=False)

        assert AUTH_LOGIN_TOTAL.labels(result="failure")._value.get() == initial + 1

    def test_record_token_validation(self):
        """record_token_validation should increment correct label."""
        from observability.auth_metrics import record_token_validation, AUTH_TOKEN_VALIDATIONS_TOTAL

        initial = AUTH_TOKEN_VALIDATIONS_TOTAL.labels(result="success")._value.get()

        record_token_validation("success")

        assert AUTH_TOKEN_VALIDATIONS_TOTAL.labels(result="success")._value.get() == initial + 1

    def test_record_api_key_validation(self):
        """record_api_key_validation should increment correct label."""
        from observability.auth_metrics import record_api_key_validation, AUTH_API_KEY_VALIDATIONS_TOTAL

        initial = AUTH_API_KEY_VALIDATIONS_TOTAL.labels(result="expired")._value.get()

        record_api_key_validation("expired")

        assert AUTH_API_KEY_VALIDATIONS_TOTAL.labels(result="expired")._value.get() == initial + 1

    def test_record_api_key_operation(self):
        """record_api_key_operation should increment with operation and result."""
        from observability.auth_metrics import record_api_key_operation, AUTH_API_KEY_OPERATIONS_TOTAL

        initial = AUTH_API_KEY_OPERATIONS_TOTAL.labels(operation="create", result="success")._value.get()

        record_api_key_operation("create", success=True)

        assert AUTH_API_KEY_OPERATIONS_TOTAL.labels(operation="create", result="success")._value.get() == initial + 1

    def test_record_audit_log_write(self):
        """record_audit_log_write should increment with action label."""
        from observability.auth_metrics import record_audit_log_write, AUDIT_LOG_WRITES_TOTAL

        initial = AUDIT_LOG_WRITES_TOTAL.labels(action="login_success")._value.get()

        record_audit_log_write("login_success")

        assert AUDIT_LOG_WRITES_TOTAL.labels(action="login_success")._value.get() == initial + 1

    def test_record_auth_request(self):
        """record_auth_request should increment with method and role."""
        from observability.auth_metrics import record_auth_request, AUTH_REQUESTS_TOTAL

        initial = AUTH_REQUESTS_TOTAL.labels(auth_method="jwt", role="admin")._value.get()

        record_auth_request("jwt", "admin")

        assert AUTH_REQUESTS_TOTAL.labels(auth_method="jwt", role="admin")._value.get() == initial + 1

    def test_record_rbac_check(self):
        """record_rbac_check should increment with required_role and result."""
        from observability.auth_metrics import record_rbac_check, RBAC_CHECKS_TOTAL

        initial = RBAC_CHECKS_TOTAL.labels(required_role="admin", result="denied")._value.get()

        record_rbac_check("admin", allowed=False)

        assert RBAC_CHECKS_TOTAL.labels(required_role="admin", result="denied")._value.get() == initial + 1


class TestAuditLogMetrics:
    """Tests for audit log specific metrics."""

    def test_audit_log_queries_counter_exists(self):
        """AUDIT_LOG_QUERIES_TOTAL should be defined."""
        from observability.auth_metrics import AUDIT_LOG_QUERIES_TOTAL

        assert AUDIT_LOG_QUERIES_TOTAL is not None
        assert "has_filters" in AUDIT_LOG_QUERIES_TOTAL._labelnames

    def test_audit_log_exports_counter_exists(self):
        """AUDIT_LOG_EXPORTS_TOTAL should be defined."""
        from observability.auth_metrics import AUDIT_LOG_EXPORTS_TOTAL

        assert AUDIT_LOG_EXPORTS_TOTAL is not None
        assert "format" in AUDIT_LOG_EXPORTS_TOTAL._labelnames

    def test_record_audit_log_query(self):
        """record_audit_log_query should increment correctly."""
        from observability.auth_metrics import record_audit_log_query, AUDIT_LOG_QUERIES_TOTAL

        initial = AUDIT_LOG_QUERIES_TOTAL.labels(has_filters="true")._value.get()

        record_audit_log_query(has_filters=True)

        assert AUDIT_LOG_QUERIES_TOTAL.labels(has_filters="true")._value.get() == initial + 1

    def test_record_audit_log_export(self):
        """record_audit_log_export should increment with format."""
        from observability.auth_metrics import record_audit_log_export, AUDIT_LOG_EXPORTS_TOTAL

        initial = AUDIT_LOG_EXPORTS_TOTAL.labels(format="zip")._value.get()

        record_audit_log_export("zip")

        assert AUDIT_LOG_EXPORTS_TOTAL.labels(format="zip")._value.get() == initial + 1


class TestInviteMetrics:
    """Tests for invite metrics (v3.1.0 PR6)."""

    def test_invite_operations_counter_exists(self):
        """INVITE_OPERATIONS_TOTAL should be defined."""
        from observability.auth_metrics import INVITE_OPERATIONS_TOTAL

        assert INVITE_OPERATIONS_TOTAL is not None
        assert "operation" in INVITE_OPERATIONS_TOTAL._labelnames
        assert "result" in INVITE_OPERATIONS_TOTAL._labelnames

    def test_invite_accept_counter_exists(self):
        """INVITE_ACCEPT_TOTAL should be defined."""
        from observability.auth_metrics import INVITE_ACCEPT_TOTAL

        assert INVITE_ACCEPT_TOTAL is not None
        assert "result" in INVITE_ACCEPT_TOTAL._labelnames

    def test_record_invite_operation(self):
        """record_invite_operation should increment correctly."""
        from observability.auth_metrics import record_invite_operation, INVITE_OPERATIONS_TOTAL

        initial = INVITE_OPERATIONS_TOTAL.labels(operation="create", result="success")._value.get()

        record_invite_operation("create", success=True)

        assert INVITE_OPERATIONS_TOTAL.labels(operation="create", result="success")._value.get() == initial + 1

    def test_record_invite_operation_failure(self):
        """record_invite_operation should handle failure."""
        from observability.auth_metrics import record_invite_operation, INVITE_OPERATIONS_TOTAL

        initial = INVITE_OPERATIONS_TOTAL.labels(operation="revoke", result="failure")._value.get()

        record_invite_operation("revoke", success=False)

        assert INVITE_OPERATIONS_TOTAL.labels(operation="revoke", result="failure")._value.get() == initial + 1

    def test_record_invite_accept_success(self):
        """record_invite_accept should increment success."""
        from observability.auth_metrics import record_invite_accept, INVITE_ACCEPT_TOTAL

        initial = INVITE_ACCEPT_TOTAL.labels(result="success")._value.get()

        record_invite_accept("success")

        assert INVITE_ACCEPT_TOTAL.labels(result="success")._value.get() == initial + 1

    def test_record_invite_accept_expired(self):
        """record_invite_accept should handle expired."""
        from observability.auth_metrics import record_invite_accept, INVITE_ACCEPT_TOTAL

        initial = INVITE_ACCEPT_TOTAL.labels(result="expired")._value.get()

        record_invite_accept("expired")

        assert INVITE_ACCEPT_TOTAL.labels(result="expired")._value.get() == initial + 1


class TestShareMetrics:
    """Tests for share link metrics (v3.1.0 PR6)."""

    def test_share_operations_counter_exists(self):
        """SHARE_OPERATIONS_TOTAL should be defined."""
        from observability.auth_metrics import SHARE_OPERATIONS_TOTAL

        assert SHARE_OPERATIONS_TOTAL is not None
        assert "operation" in SHARE_OPERATIONS_TOTAL._labelnames
        assert "resource_type" in SHARE_OPERATIONS_TOTAL._labelnames
        assert "result" in SHARE_OPERATIONS_TOTAL._labelnames

    def test_share_access_counter_exists(self):
        """SHARE_ACCESS_TOTAL should be defined."""
        from observability.auth_metrics import SHARE_ACCESS_TOTAL

        assert SHARE_ACCESS_TOTAL is not None
        assert "resource_type" in SHARE_ACCESS_TOTAL._labelnames
        assert "result" in SHARE_ACCESS_TOTAL._labelnames

    def test_record_share_operation(self):
        """record_share_operation should increment correctly."""
        from observability.auth_metrics import record_share_operation, SHARE_OPERATIONS_TOTAL

        initial = SHARE_OPERATIONS_TOTAL.labels(operation="create", resource_type="run", result="success")._value.get()

        record_share_operation("create", "run", success=True)

        assert SHARE_OPERATIONS_TOTAL.labels(operation="create", resource_type="run", result="success")._value.get() == initial + 1

    def test_record_share_operation_report(self):
        """record_share_operation should handle report type."""
        from observability.auth_metrics import record_share_operation, SHARE_OPERATIONS_TOTAL

        initial = SHARE_OPERATIONS_TOTAL.labels(operation="revoke", resource_type="report", result="success")._value.get()

        record_share_operation("revoke", "report", success=True)

        assert SHARE_OPERATIONS_TOTAL.labels(operation="revoke", resource_type="report", result="success")._value.get() == initial + 1

    def test_record_share_access_success(self):
        """record_share_access should increment success."""
        from observability.auth_metrics import record_share_access, SHARE_ACCESS_TOTAL

        initial = SHARE_ACCESS_TOTAL.labels(resource_type="run", result="success")._value.get()

        record_share_access("run", "success")

        assert SHARE_ACCESS_TOTAL.labels(resource_type="run", result="success")._value.get() == initial + 1

    def test_record_share_access_expired(self):
        """record_share_access should handle expired."""
        from observability.auth_metrics import record_share_access, SHARE_ACCESS_TOTAL

        initial = SHARE_ACCESS_TOTAL.labels(resource_type="report", result="expired")._value.get()

        record_share_access("report", "expired")

        assert SHARE_ACCESS_TOTAL.labels(resource_type="report", result="expired")._value.get() == initial + 1


class TestUserAdminMetrics:
    """Tests for user admin metrics (v3.1.0 PR6)."""

    def test_user_operations_counter_exists(self):
        """USER_OPERATIONS_TOTAL should be defined."""
        from observability.auth_metrics import USER_OPERATIONS_TOTAL

        assert USER_OPERATIONS_TOTAL is not None
        assert "operation" in USER_OPERATIONS_TOTAL._labelnames
        assert "result" in USER_OPERATIONS_TOTAL._labelnames

    def test_record_user_operation_create(self):
        """record_user_operation should increment create success."""
        from observability.auth_metrics import record_user_operation, USER_OPERATIONS_TOTAL

        initial = USER_OPERATIONS_TOTAL.labels(operation="create", result="success")._value.get()

        record_user_operation("create", success=True)

        assert USER_OPERATIONS_TOTAL.labels(operation="create", result="success")._value.get() == initial + 1

    def test_record_user_operation_update(self):
        """record_user_operation should handle update."""
        from observability.auth_metrics import record_user_operation, USER_OPERATIONS_TOTAL

        initial = USER_OPERATIONS_TOTAL.labels(operation="update", result="success")._value.get()

        record_user_operation("update", success=True)

        assert USER_OPERATIONS_TOTAL.labels(operation="update", result="success")._value.get() == initial + 1

    def test_record_user_operation_failure(self):
        """record_user_operation should handle failure."""
        from observability.auth_metrics import record_user_operation, USER_OPERATIONS_TOTAL

        initial = USER_OPERATIONS_TOTAL.labels(operation="reset_password", result="failure")._value.get()

        record_user_operation("reset_password", success=False)

        assert USER_OPERATIONS_TOTAL.labels(operation="reset_password", result="failure")._value.get() == initial + 1
