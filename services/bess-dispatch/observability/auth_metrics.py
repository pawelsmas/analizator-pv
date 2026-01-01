"""
Auth metrics for Prometheus instrumentation (v3.0.0).

Provides:
- bess_auth_login_total: Counter for login attempts (success/failure)
- bess_auth_token_validations_total: Counter for JWT token validations
- bess_auth_api_key_validations_total: Counter for API key validations
- bess_auth_api_key_operations_total: Counter for API key operations (create/revoke)
- bess_audit_log_writes_total: Counter for audit log entries
- bess_auth_requests_total: Counter for authenticated requests by auth_method

Label cardinality rules:
- result: "success" or "failure"
- auth_method: "jwt", "api_key", "disabled"
- operation: "create", "revoke", "list"
- action: audit action type (login_success, api_key_created, etc.)
"""

from prometheus_client import Counter, Histogram

SERVICE_NAME = "bess"

# Login metrics
AUTH_LOGIN_TOTAL = Counter(
    "bess_auth_login_total",
    "Total login attempts",
    ["result"],  # success, failure
)

# Token validation metrics
AUTH_TOKEN_VALIDATIONS_TOTAL = Counter(
    "bess_auth_token_validations_total",
    "Total JWT token validation attempts",
    ["result"],  # success, failure, expired
)

# API key validation metrics
AUTH_API_KEY_VALIDATIONS_TOTAL = Counter(
    "bess_auth_api_key_validations_total",
    "Total API key validation attempts",
    ["result"],  # success, failure, expired, revoked
)

# API key operations
AUTH_API_KEY_OPERATIONS_TOTAL = Counter(
    "bess_auth_api_key_operations_total",
    "Total API key operations",
    ["operation", "result"],  # operation: create, revoke, list; result: success, failure
)

# Audit log metrics
AUDIT_LOG_WRITES_TOTAL = Counter(
    "bess_audit_log_writes_total",
    "Total audit log entries written",
    ["action"],  # login_success, login_failure, api_key_created, etc.
)

AUDIT_LOG_QUERIES_TOTAL = Counter(
    "bess_audit_log_queries_total",
    "Total audit log queries",
    ["has_filters"],  # true, false
)

AUDIT_LOG_EXPORTS_TOTAL = Counter(
    "bess_audit_log_exports_total",
    "Total audit log exports",
    ["format"],  # csv, json, zip
)

# Request auth method metrics
AUTH_REQUESTS_TOTAL = Counter(
    "bess_auth_requests_total",
    "Total authenticated requests by auth method",
    ["auth_method", "role"],  # auth_method: jwt, api_key, disabled; role: admin, editor, viewer, service
)

# RBAC metrics
RBAC_CHECKS_TOTAL = Counter(
    "bess_rbac_checks_total",
    "Total RBAC permission checks",
    ["required_role", "result"],  # required_role: admin, editor, viewer, service; result: allowed, denied
)


# Helper functions for recording metrics
def record_login(success: bool):
    """Record a login attempt."""
    AUTH_LOGIN_TOTAL.labels(result="success" if success else "failure").inc()


def record_token_validation(result: str):
    """Record a JWT token validation attempt.

    Args:
        result: "success", "failure", or "expired"
    """
    AUTH_TOKEN_VALIDATIONS_TOTAL.labels(result=result).inc()


def record_api_key_validation(result: str):
    """Record an API key validation attempt.

    Args:
        result: "success", "failure", "expired", or "revoked"
    """
    AUTH_API_KEY_VALIDATIONS_TOTAL.labels(result=result).inc()


def record_api_key_operation(operation: str, success: bool):
    """Record an API key operation.

    Args:
        operation: "create", "revoke", or "list"
        success: Whether the operation succeeded
    """
    AUTH_API_KEY_OPERATIONS_TOTAL.labels(
        operation=operation,
        result="success" if success else "failure",
    ).inc()


def record_audit_log_write(action: str):
    """Record an audit log entry write.

    Args:
        action: The audit action (login_success, api_key_created, etc.)
    """
    AUDIT_LOG_WRITES_TOTAL.labels(action=action).inc()


def record_audit_log_query(has_filters: bool):
    """Record an audit log query.

    Args:
        has_filters: Whether the query had filters applied
    """
    AUDIT_LOG_QUERIES_TOTAL.labels(has_filters="true" if has_filters else "false").inc()


def record_audit_log_export(format: str):
    """Record an audit log export.

    Args:
        format: The export format (csv, json, zip)
    """
    AUDIT_LOG_EXPORTS_TOTAL.labels(format=format).inc()


def record_auth_request(auth_method: str, role: str):
    """Record an authenticated request.

    Args:
        auth_method: "jwt", "api_key", or "disabled"
        role: User role (admin, editor, viewer, service)
    """
    AUTH_REQUESTS_TOTAL.labels(auth_method=auth_method, role=role).inc()


def record_rbac_check(required_role: str, allowed: bool):
    """Record an RBAC permission check.

    Args:
        required_role: The role that was required
        allowed: Whether access was allowed
    """
    RBAC_CHECKS_TOTAL.labels(
        required_role=required_role,
        result="allowed" if allowed else "denied",
    ).inc()
