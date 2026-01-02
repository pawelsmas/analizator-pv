"""
Auth metrics for Prometheus instrumentation (v3.8.0).

Provides:
- bess_auth_login_total: Counter for login attempts (success/failure)
- bess_auth_token_validations_total: Counter for JWT token validations
- bess_auth_api_key_validations_total: Counter for API key validations
- bess_auth_api_key_operations_total: Counter for API key operations (create/revoke)
- bess_audit_log_writes_total: Counter for audit log entries
- bess_auth_requests_total: Counter for authenticated requests by auth_method
- bess_invite_operations_total: Counter for invite operations (v3.1.0)
- bess_invite_accept_total: Counter for invite accepts (v3.1.0)
- bess_share_operations_total: Counter for share link operations (v3.1.0)
- bess_share_access_total: Counter for share link accesses (v3.1.0)
- bess_user_operations_total: Counter for user admin operations (v3.1.0)

v3.8.0 Share Security metrics:
- bess_share_v2_created_total: Counter for v2 share creations with security features
- bess_share_access_denied_total: Counter for share access denials by reason
- bess_share_token_rotation_total: Counter for token rotation operations
- bess_share_revoke_all_total: Counter for bulk revoke operations
- bess_share_retention_purge_total: Counter for retention purge operations
- bess_share_password_attempts_total: Counter for password verification attempts
- bess_share_access_count_exceeded_total: Counter for max access count exceeded events

Label cardinality rules:
- result: "success" or "failure"
- auth_method: "jwt", "api_key", "disabled"
- operation: "create", "revoke", "list"
- action: audit action type (login_success, api_key_created, etc.)
- denial_reason: "password_required", "invalid_password", "access_limit_exceeded", "expired", "revoked"
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


# v3.1.0: Invite metrics
INVITE_OPERATIONS_TOTAL = Counter(
    "bess_invite_operations_total",
    "Total invite operations",
    ["operation", "result"],  # operation: create, revoke, list; result: success, failure
)

INVITE_ACCEPT_TOTAL = Counter(
    "bess_invite_accept_total",
    "Total invite accept attempts",
    ["result"],  # success, failure, expired, revoked
)

# v3.1.0: Share link metrics
SHARE_OPERATIONS_TOTAL = Counter(
    "bess_share_operations_total",
    "Total share link operations",
    ["operation", "resource_type", "result"],  # operation: create, revoke, list; resource_type: run, report; result: success, failure
)

SHARE_ACCESS_TOTAL = Counter(
    "bess_share_access_total",
    "Total share link access attempts",
    ["resource_type", "result"],  # resource_type: run, report; result: success, expired, revoked, not_found
)

# v3.1.0: User admin metrics
USER_OPERATIONS_TOTAL = Counter(
    "bess_user_operations_total",
    "Total user admin operations",
    ["operation", "result"],  # operation: create, update, list, reset_password; result: success, failure
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


# v3.1.0: Invite helper functions
def record_invite_operation(operation: str, success: bool):
    """Record an invite operation.

    Args:
        operation: "create", "revoke", or "list"
        success: Whether the operation succeeded
    """
    INVITE_OPERATIONS_TOTAL.labels(
        operation=operation,
        result="success" if success else "failure",
    ).inc()


def record_invite_accept(result: str):
    """Record an invite accept attempt.

    Args:
        result: "success", "failure", "expired", or "revoked"
    """
    INVITE_ACCEPT_TOTAL.labels(result=result).inc()


# v3.1.0: Share helper functions
def record_share_operation(operation: str, resource_type: str, success: bool):
    """Record a share link operation.

    Args:
        operation: "create", "revoke", or "list"
        resource_type: "run" or "report"
        success: Whether the operation succeeded
    """
    SHARE_OPERATIONS_TOTAL.labels(
        operation=operation,
        resource_type=resource_type,
        result="success" if success else "failure",
    ).inc()


def record_share_access(resource_type: str, result: str):
    """Record a share link access attempt.

    Args:
        resource_type: "run" or "report"
        result: "success", "expired", "revoked", or "not_found"
    """
    SHARE_ACCESS_TOTAL.labels(resource_type=resource_type, result=result).inc()


# v3.1.0: User admin helper functions
def record_user_operation(operation: str, success: bool):
    """Record a user admin operation.

    Args:
        operation: "create", "update", "list", or "reset_password"
        success: Whether the operation succeeded
    """
    USER_OPERATIONS_TOTAL.labels(
        operation=operation,
        result="success" if success else "failure",
    ).inc()


# -------------------------------------------------------------------------
# v3.8.0: Share Security metrics
# -------------------------------------------------------------------------

# Share v2 creation with security features
SHARE_V2_CREATED_TOTAL = Counter(
    "bess_share_v2_created_total",
    "Total v2 shares created with security features",
    ["resource_type", "has_password", "single_use", "has_max_access"],
)

# Share access denial by reason
SHARE_ACCESS_DENIED_TOTAL = Counter(
    "bess_share_access_denied_total",
    "Total share access denials",
    ["resource_type", "denial_reason"],
)

# Token rotation operations
SHARE_TOKEN_ROTATION_TOTAL = Counter(
    "bess_share_token_rotation_total",
    "Total share token rotation operations",
    ["result"],
)

# Bulk revoke operations
SHARE_REVOKE_ALL_TOTAL = Counter(
    "bess_share_revoke_all_total",
    "Total bulk share revoke operations",
    ["scope", "result"],  # scope: project, resource
)

# Retention purge operations
SHARE_RETENTION_PURGE_TOTAL = Counter(
    "bess_share_retention_purge_total",
    "Total retention purge operations",
    ["purge_type", "result"],  # purge_type: expired_shares, revoked_shares, access_logs
)

# Retention purge items deleted
SHARE_RETENTION_PURGED_ITEMS_TOTAL = Counter(
    "bess_share_retention_purged_items_total",
    "Total items purged by retention operations",
    ["purge_type"],
)

# Password verification attempts
SHARE_PASSWORD_ATTEMPTS_TOTAL = Counter(
    "bess_share_password_attempts_total",
    "Total share password verification attempts",
    ["result"],  # success, failure
)

# Access count exceeded events
SHARE_ACCESS_COUNT_EXCEEDED_TOTAL = Counter(
    "bess_share_access_count_exceeded_total",
    "Total times max access count was exceeded",
    ["resource_type"],
)

# Share access log entries
SHARE_ACCESS_LOG_ENTRIES_TOTAL = Counter(
    "bess_share_access_log_entries_total",
    "Total share access log entries created",
    ["access_result"],  # success, denied
)

# Share stats queries
SHARE_STATS_QUERIES_TOTAL = Counter(
    "bess_share_stats_queries_total",
    "Total share statistics queries",
)


# v3.8.0: Share security helper functions
def record_share_v2_created(
    resource_type: str,
    has_password: bool,
    single_use: bool,
    has_max_access: bool,
):
    """Record a v2 share creation with security features.

    Args:
        resource_type: "run" or "report"
        has_password: Whether share has password protection
        single_use: Whether share is single-use
        has_max_access: Whether share has max access count limit
    """
    SHARE_V2_CREATED_TOTAL.labels(
        resource_type=resource_type,
        has_password="true" if has_password else "false",
        single_use="true" if single_use else "false",
        has_max_access="true" if has_max_access else "false",
    ).inc()


def record_share_access_denied(resource_type: str, denial_reason: str):
    """Record a share access denial.

    Args:
        resource_type: "run" or "report"
        denial_reason: "password_required", "invalid_password", "access_limit_exceeded", "expired", "revoked"
    """
    SHARE_ACCESS_DENIED_TOTAL.labels(
        resource_type=resource_type,
        denial_reason=denial_reason,
    ).inc()


def record_share_token_rotation(success: bool):
    """Record a share token rotation operation.

    Args:
        success: Whether the rotation succeeded
    """
    SHARE_TOKEN_ROTATION_TOTAL.labels(
        result="success" if success else "failure",
    ).inc()


def record_share_revoke_all(scope: str, success: bool):
    """Record a bulk share revoke operation.

    Args:
        scope: "project" or "resource"
        success: Whether the operation succeeded
    """
    SHARE_REVOKE_ALL_TOTAL.labels(
        scope=scope,
        result="success" if success else "failure",
    ).inc()


def record_share_retention_purge(purge_type: str, success: bool, deleted_count: int = 0):
    """Record a retention purge operation.

    Args:
        purge_type: "expired_shares", "revoked_shares", or "access_logs"
        success: Whether the operation succeeded
        deleted_count: Number of items deleted
    """
    SHARE_RETENTION_PURGE_TOTAL.labels(
        purge_type=purge_type,
        result="success" if success else "failure",
    ).inc()

    if deleted_count > 0:
        SHARE_RETENTION_PURGED_ITEMS_TOTAL.labels(purge_type=purge_type).inc(deleted_count)


def record_share_password_attempt(success: bool):
    """Record a share password verification attempt.

    Args:
        success: Whether the password was correct
    """
    SHARE_PASSWORD_ATTEMPTS_TOTAL.labels(
        result="success" if success else "failure",
    ).inc()


def record_share_access_count_exceeded(resource_type: str):
    """Record a max access count exceeded event.

    Args:
        resource_type: "run" or "report"
    """
    SHARE_ACCESS_COUNT_EXCEEDED_TOTAL.labels(resource_type=resource_type).inc()


def record_share_access_log_entry(access_result: str):
    """Record a share access log entry creation.

    Args:
        access_result: "success" or "denied"
    """
    SHARE_ACCESS_LOG_ENTRIES_TOTAL.labels(access_result=access_result).inc()


def record_share_stats_query():
    """Record a share statistics query."""
    SHARE_STATS_QUERIES_TOTAL.inc()
