"""
Quota and usage metrics for Prometheus instrumentation (v4.0.0).

Provides:
- bess_quota_check_total: Counter for quota checks (allowed/denied)
- bess_quota_exceeded_total: Counter for quota exceeded events by type
- bess_quota_usage_current: Gauge for current quota usage
- bess_quota_limit_current: Gauge for current quota limits
- bess_quota_usage_pct: Gauge for quota usage percentage
- bess_quota_enforcement_total: Counter for enforcement actions
- bess_usage_api_requests_total: Counter for usage API requests
- bess_usage_export_total: Counter for usage exports
- bess_plan_assignments_total: Counter for plan assignments
- bess_project_override_total: Counter for project quota overrides

Label cardinality rules:
- quota_name: jobs_per_day, reports_per_day, shares_total, storage_mb, projects_total
- result: allowed, denied
- plan_id: free, pro, enterprise
- action: check, enforce, increment
"""

from prometheus_client import Counter, Gauge, Histogram

SERVICE_NAME = "bess"

# -----------------------------------------------------------------------------
# Quota check metrics
# -----------------------------------------------------------------------------

QUOTA_CHECK_TOTAL = Counter(
    "bess_quota_check_total",
    "Total quota check operations",
    ["quota_name", "result"],  # result: allowed, denied
)

QUOTA_EXCEEDED_TOTAL = Counter(
    "bess_quota_exceeded_total",
    "Total quota exceeded events",
    ["quota_name", "plan_id"],
)

QUOTA_ENFORCEMENT_TOTAL = Counter(
    "bess_quota_enforcement_total",
    "Total quota enforcement actions",
    ["quota_name", "action"],  # action: blocked, warned, incremented
)

# -----------------------------------------------------------------------------
# Quota state gauges
# -----------------------------------------------------------------------------

QUOTA_USAGE_CURRENT = Gauge(
    "bess_quota_usage_current",
    "Current quota usage",
    ["tenant_id", "project_id", "quota_name"],
)

QUOTA_LIMIT_CURRENT = Gauge(
    "bess_quota_limit_current",
    "Current quota limit (0 = unlimited)",
    ["tenant_id", "project_id", "quota_name"],
)

QUOTA_USAGE_PCT = Gauge(
    "bess_quota_usage_pct",
    "Current quota usage as percentage of limit",
    ["tenant_id", "project_id", "quota_name"],
)

QUOTA_REMAINING = Gauge(
    "bess_quota_remaining",
    "Remaining quota (null if unlimited)",
    ["tenant_id", "project_id", "quota_name"],
)

# -----------------------------------------------------------------------------
# Usage API metrics
# -----------------------------------------------------------------------------

USAGE_API_REQUESTS_TOTAL = Counter(
    "bess_usage_api_requests_total",
    "Total usage API requests",
    ["endpoint", "result"],  # endpoint: tenant, project, daily; result: success, failure
)

USAGE_EXPORT_TOTAL = Counter(
    "bess_usage_export_total",
    "Total usage export operations",
    ["format", "result"],  # format: csv, json; result: success, failure
)

USAGE_QUERY_DURATION = Histogram(
    "bess_usage_query_duration_seconds",
    "Duration of usage queries",
    ["query_type"],  # query_type: tenant_summary, project_summary, daily_records
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

# -----------------------------------------------------------------------------
# Plan and override metrics
# -----------------------------------------------------------------------------

PLAN_ASSIGNMENTS_TOTAL = Counter(
    "bess_plan_assignments_total",
    "Total plan assignment operations",
    ["plan_id", "operation"],  # operation: assign, change
)

PROJECT_OVERRIDE_TOTAL = Counter(
    "bess_project_override_total",
    "Total project quota override operations",
    ["quota_name", "operation"],  # operation: set, clear
)

PLAN_USAGE_BY_TIER = Gauge(
    "bess_plan_usage_by_tier",
    "Number of tenants per plan tier",
    ["plan_id"],
)

# -----------------------------------------------------------------------------
# Quota reset metrics
# -----------------------------------------------------------------------------

QUOTA_RESET_SECONDS_REMAINING = Gauge(
    "bess_quota_reset_seconds_remaining",
    "Seconds until next quota reset (midnight UTC)",
)

# -----------------------------------------------------------------------------
# Helper functions for recording metrics
# -----------------------------------------------------------------------------


def record_quota_check(quota_name: str, allowed: bool):
    """Record a quota check operation.

    Args:
        quota_name: The quota being checked
        allowed: Whether the request was allowed
    """
    QUOTA_CHECK_TOTAL.labels(
        quota_name=quota_name,
        result="allowed" if allowed else "denied",
    ).inc()


def record_quota_exceeded(quota_name: str, plan_id: str):
    """Record a quota exceeded event.

    Args:
        quota_name: The quota that was exceeded
        plan_id: The plan ID of the tenant
    """
    QUOTA_EXCEEDED_TOTAL.labels(
        quota_name=quota_name,
        plan_id=plan_id,
    ).inc()


def record_quota_enforcement(quota_name: str, action: str):
    """Record a quota enforcement action.

    Args:
        quota_name: The quota being enforced
        action: The action taken (blocked, warned, incremented)
    """
    QUOTA_ENFORCEMENT_TOTAL.labels(
        quota_name=quota_name,
        action=action,
    ).inc()


def update_quota_usage(tenant_id: str, project_id: str, quota_name: str, used: int, limit: int):
    """Update quota usage gauges.

    Args:
        tenant_id: The tenant ID
        project_id: The project ID
        quota_name: The quota name
        used: Current usage
        limit: Current limit (0 = unlimited)
    """
    QUOTA_USAGE_CURRENT.labels(
        tenant_id=tenant_id,
        project_id=project_id,
        quota_name=quota_name,
    ).set(used)

    QUOTA_LIMIT_CURRENT.labels(
        tenant_id=tenant_id,
        project_id=project_id,
        quota_name=quota_name,
    ).set(limit)

    if limit > 0:
        pct = (used / limit) * 100
        QUOTA_USAGE_PCT.labels(
            tenant_id=tenant_id,
            project_id=project_id,
            quota_name=quota_name,
        ).set(pct)

        remaining = max(0, limit - used)
        QUOTA_REMAINING.labels(
            tenant_id=tenant_id,
            project_id=project_id,
            quota_name=quota_name,
        ).set(remaining)
    else:
        # Unlimited - set to -1 to indicate unlimited
        QUOTA_USAGE_PCT.labels(
            tenant_id=tenant_id,
            project_id=project_id,
            quota_name=quota_name,
        ).set(0)

        QUOTA_REMAINING.labels(
            tenant_id=tenant_id,
            project_id=project_id,
            quota_name=quota_name,
        ).set(-1)


def record_usage_api_request(endpoint: str, success: bool):
    """Record a usage API request.

    Args:
        endpoint: The endpoint type (tenant, project, daily)
        success: Whether the request succeeded
    """
    USAGE_API_REQUESTS_TOTAL.labels(
        endpoint=endpoint,
        result="success" if success else "failure",
    ).inc()


def record_usage_export(format: str, success: bool):
    """Record a usage export operation.

    Args:
        format: The export format (csv, json)
        success: Whether the export succeeded
    """
    USAGE_EXPORT_TOTAL.labels(
        format=format,
        result="success" if success else "failure",
    ).inc()


def observe_usage_query_duration(query_type: str, duration_seconds: float):
    """Observe the duration of a usage query.

    Args:
        query_type: The type of query
        duration_seconds: The duration in seconds
    """
    USAGE_QUERY_DURATION.labels(query_type=query_type).observe(duration_seconds)


def record_plan_assignment(plan_id: str, is_new: bool):
    """Record a plan assignment.

    Args:
        plan_id: The plan being assigned
        is_new: Whether this is a new assignment or a change
    """
    PLAN_ASSIGNMENTS_TOTAL.labels(
        plan_id=plan_id,
        operation="assign" if is_new else "change",
    ).inc()


def record_project_override(quota_name: str, is_set: bool):
    """Record a project quota override operation.

    Args:
        quota_name: The quota being overridden
        is_set: Whether the override is being set (True) or cleared (False)
    """
    PROJECT_OVERRIDE_TOTAL.labels(
        quota_name=quota_name,
        operation="set" if is_set else "clear",
    ).inc()


def update_plan_tier_usage(plan_counts: dict):
    """Update the plan tier usage gauge.

    Args:
        plan_counts: Dict mapping plan_id to count of tenants
    """
    for plan_id, count in plan_counts.items():
        PLAN_USAGE_BY_TIER.labels(plan_id=plan_id).set(count)


def update_quota_reset_seconds(seconds: int):
    """Update the seconds until quota reset gauge.

    Args:
        seconds: Seconds until next reset
    """
    QUOTA_RESET_SECONDS_REMAINING.set(seconds)
