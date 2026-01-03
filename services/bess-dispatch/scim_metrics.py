"""
SCIM Observability Metrics (v4.4.0 PR10).

Prometheus metrics for SCIM provisioning operations.

Metrics cover:
- SCIM API requests (users, groups)
- Token usage and validation
- Group sync operations
- Deprovision events
- Error rates and latencies
"""

from prometheus_client import Counter, Histogram, Gauge, Info


# =============================================================================
# SCIM Token Metrics
# =============================================================================

scim_token_requests_total = Counter(
    "scim_token_requests_total",
    "Total SCIM API requests by token",
    ["token_id", "tenant_id", "endpoint"]
)

scim_token_validation_total = Counter(
    "scim_token_validation_total",
    "Token validation attempts",
    ["result"]  # success, expired, revoked, invalid
)

scim_tokens_active = Gauge(
    "scim_tokens_active",
    "Number of active (non-revoked, non-expired) SCIM tokens",
    ["tenant_id"]
)

# =============================================================================
# SCIM Users Metrics
# =============================================================================

scim_users_requests_total = Counter(
    "scim_users_requests_total",
    "SCIM Users endpoint requests",
    ["method", "status_code"]  # GET, POST, PATCH, DELETE
)

scim_users_request_duration_seconds = Histogram(
    "scim_users_request_duration_seconds",
    "SCIM Users request duration",
    ["method"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

scim_users_total = Gauge(
    "scim_users_total",
    "Total SCIM users per tenant",
    ["tenant_id"]
)

scim_users_active = Gauge(
    "scim_users_active",
    "Active SCIM users per tenant",
    ["tenant_id"]
)

scim_users_provisioned_total = Counter(
    "scim_users_provisioned_total",
    "Total users provisioned via SCIM",
    ["tenant_id"]
)

scim_users_updated_total = Counter(
    "scim_users_updated_total",
    "Total user updates via SCIM",
    ["tenant_id"]
)

scim_users_deprovisioned_total = Counter(
    "scim_users_deprovisioned_total",
    "Total users deprovisioned via SCIM",
    ["tenant_id", "hard_delete"]
)

# =============================================================================
# SCIM Groups Metrics
# =============================================================================

scim_groups_requests_total = Counter(
    "scim_groups_requests_total",
    "SCIM Groups endpoint requests",
    ["method", "status_code"]
)

scim_groups_request_duration_seconds = Histogram(
    "scim_groups_request_duration_seconds",
    "SCIM Groups request duration",
    ["method"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

scim_groups_total = Gauge(
    "scim_groups_total",
    "Total SCIM groups per tenant",
    ["tenant_id"]
)

scim_group_members_total = Gauge(
    "scim_group_members_total",
    "Members in SCIM group",
    ["tenant_id", "group_id"]
)

# =============================================================================
# Group Sync Metrics
# =============================================================================

scim_sync_requests_total = Counter(
    "scim_sync_requests_total",
    "Group sync requests",
    ["tenant_id", "sync_type"]  # single_group, all_groups, user_sync
)

scim_sync_duration_seconds = Histogram(
    "scim_sync_duration_seconds",
    "Group sync duration",
    ["sync_type"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
)

scim_sync_members_added_total = Counter(
    "scim_sync_members_added_total",
    "Project members added by sync",
    ["tenant_id"]
)

scim_sync_members_removed_total = Counter(
    "scim_sync_members_removed_total",
    "Project members removed by sync",
    ["tenant_id"]
)

scim_sync_errors_total = Counter(
    "scim_sync_errors_total",
    "Sync errors",
    ["tenant_id", "error_type"]
)

scim_sync_last_success_timestamp = Gauge(
    "scim_sync_last_success_timestamp",
    "Timestamp of last successful sync",
    ["tenant_id"]
)

# =============================================================================
# Group Mappings Metrics
# =============================================================================

scim_mappings_total = Gauge(
    "scim_mappings_total",
    "Total group-project mappings",
    ["tenant_id", "enabled"]
)

scim_mappings_created_total = Counter(
    "scim_mappings_created_total",
    "Mappings created",
    ["tenant_id"]
)

scim_mappings_deleted_total = Counter(
    "scim_mappings_deleted_total",
    "Mappings deleted",
    ["tenant_id"]
)

scim_mappings_toggled_total = Counter(
    "scim_mappings_toggled_total",
    "Mappings enabled/disabled",
    ["tenant_id", "new_state"]  # enabled, disabled
)

# =============================================================================
# Deprovision Metrics
# =============================================================================

scim_deprovision_requests_total = Counter(
    "scim_deprovision_requests_total",
    "Deprovision requests",
    ["tenant_id", "hard_delete"]
)

scim_deprovision_sessions_revoked_total = Counter(
    "scim_deprovision_sessions_revoked_total",
    "Sessions revoked during deprovision",
    ["tenant_id"]
)

scim_deprovision_api_keys_revoked_total = Counter(
    "scim_deprovision_api_keys_revoked_total",
    "API keys revoked during deprovision",
    ["tenant_id"]
)

scim_deprovision_memberships_revoked_total = Counter(
    "scim_deprovision_memberships_revoked_total",
    "SCIM memberships revoked during deprovision",
    ["tenant_id"]
)

# =============================================================================
# Error Metrics
# =============================================================================

scim_errors_total = Counter(
    "scim_errors_total",
    "SCIM API errors",
    ["endpoint", "status_code", "error_type"]
)

scim_rate_limit_exceeded_total = Counter(
    "scim_rate_limit_exceeded_total",
    "Rate limit exceeded events",
    ["tenant_id"]
)

# =============================================================================
# Health Metrics
# =============================================================================

scim_health_info = Info(
    "scim_health",
    "SCIM service health information"
)


# =============================================================================
# Helper Functions
# =============================================================================

def record_scim_request(endpoint: str, method: str, status_code: int, duration: float):
    """Record a SCIM API request."""
    if "Users" in endpoint:
        scim_users_requests_total.labels(method=method, status_code=status_code).inc()
        scim_users_request_duration_seconds.labels(method=method).observe(duration)
    elif "Groups" in endpoint:
        scim_groups_requests_total.labels(method=method, status_code=status_code).inc()
        scim_groups_request_duration_seconds.labels(method=method).observe(duration)


def record_token_validation(result: str):
    """Record a token validation attempt."""
    scim_token_validation_total.labels(result=result).inc()


def record_user_provisioned(tenant_id: str):
    """Record a user provisioning event."""
    scim_users_provisioned_total.labels(tenant_id=tenant_id).inc()


def record_user_updated(tenant_id: str):
    """Record a user update event."""
    scim_users_updated_total.labels(tenant_id=tenant_id).inc()


def record_user_deprovisioned(tenant_id: str, hard_delete: bool = False):
    """Record a user deprovision event."""
    scim_users_deprovisioned_total.labels(
        tenant_id=tenant_id,
        hard_delete=str(hard_delete).lower()
    ).inc()


def record_sync_result(tenant_id: str, sync_type: str, members_added: int,
                       members_removed: int, duration: float, errors: int = 0):
    """Record a sync operation result."""
    scim_sync_requests_total.labels(tenant_id=tenant_id, sync_type=sync_type).inc()
    scim_sync_duration_seconds.labels(sync_type=sync_type).observe(duration)
    scim_sync_members_added_total.labels(tenant_id=tenant_id).inc(members_added)
    scim_sync_members_removed_total.labels(tenant_id=tenant_id).inc(members_removed)

    if errors > 0:
        scim_sync_errors_total.labels(tenant_id=tenant_id, error_type="sync_error").inc(errors)


def record_deprovision_result(tenant_id: str, sessions_revoked: int,
                               api_keys_revoked: int, memberships_revoked: int,
                               hard_delete: bool = False):
    """Record a deprovision operation result."""
    scim_deprovision_requests_total.labels(
        tenant_id=tenant_id,
        hard_delete=str(hard_delete).lower()
    ).inc()
    scim_deprovision_sessions_revoked_total.labels(tenant_id=tenant_id).inc(sessions_revoked)
    scim_deprovision_api_keys_revoked_total.labels(tenant_id=tenant_id).inc(api_keys_revoked)
    scim_deprovision_memberships_revoked_total.labels(tenant_id=tenant_id).inc(memberships_revoked)


def record_error(endpoint: str, status_code: int, error_type: str):
    """Record a SCIM error."""
    scim_errors_total.labels(
        endpoint=endpoint,
        status_code=status_code,
        error_type=error_type
    ).inc()


def update_tenant_gauges(tenant_id: str, users_total: int, users_active: int,
                         groups_total: int, tokens_active: int,
                         mappings_enabled: int, mappings_disabled: int):
    """Update tenant-level gauge metrics."""
    scim_users_total.labels(tenant_id=tenant_id).set(users_total)
    scim_users_active.labels(tenant_id=tenant_id).set(users_active)
    scim_groups_total.labels(tenant_id=tenant_id).set(groups_total)
    scim_tokens_active.labels(tenant_id=tenant_id).set(tokens_active)
    scim_mappings_total.labels(tenant_id=tenant_id, enabled="true").set(mappings_enabled)
    scim_mappings_total.labels(tenant_id=tenant_id, enabled="false").set(mappings_disabled)
