"""
Project metrics for Prometheus instrumentation (v3.7.0).

Provides:
- bess_project_operations_total: Counter for project CRUD operations
- bess_project_membership_operations_total: Counter for membership changes
- bess_project_access_checks_total: Counter for project access checks
- bess_project_access_denied_total: Counter for project access denials (forbidden spikes)
- bess_project_share_policy_enforcements_total: Counter for share policy enforcements
- bess_project_count: Gauge for total projects per tenant
- bess_project_membership_count: Gauge for memberships per project

Label cardinality rules:
- operation: "create", "update", "archive", "list"
- result: "success" or "failure"
- role: "owner", "editor", "viewer"
- reason: denial reason ("not_member", "insufficient_role", "project_archived")
- policy: "allow_public_shares", "share_max_expiry"
- enforcement_result: "allowed", "denied", "clamped"
"""

from prometheus_client import Counter, Gauge, Histogram

SERVICE_NAME = "bess"


# Project CRUD operations
PROJECT_OPERATIONS_TOTAL = Counter(
    "bess_project_operations_total",
    "Total project CRUD operations",
    ["operation", "result"],  # operation: create, update, archive, list; result: success, failure
)


# Membership operations
PROJECT_MEMBERSHIP_OPERATIONS_TOTAL = Counter(
    "bess_project_membership_operations_total",
    "Total project membership operations",
    ["operation", "role", "result"],  # operation: add, update, remove; role: owner, editor, viewer; result: success, failure
)


# Project access checks
PROJECT_ACCESS_CHECKS_TOTAL = Counter(
    "bess_project_access_checks_total",
    "Total project access permission checks",
    ["required_role", "result"],  # required_role: owner, editor, viewer; result: allowed, denied
)


# Project access denied (for alerting on forbidden spikes)
PROJECT_ACCESS_DENIED_TOTAL = Counter(
    "bess_project_access_denied_total",
    "Total project access denials (for forbidden spike detection)",
    ["reason"],  # not_member, insufficient_role, project_archived, project_not_found
)


# Share policy enforcements
PROJECT_SHARE_POLICY_ENFORCEMENTS_TOTAL = Counter(
    "bess_project_share_policy_enforcements_total",
    "Total share policy enforcements",
    ["policy", "enforcement_result"],  # policy: allow_public_shares, share_max_expiry; enforcement_result: allowed, denied, clamped
)


# Project count gauge (by tenant)
PROJECT_COUNT = Gauge(
    "bess_project_count",
    "Current number of projects",
    ["tenant_id"],
)


# Membership count gauge (by project)
PROJECT_MEMBERSHIP_COUNT = Gauge(
    "bess_project_membership_count",
    "Current number of members per project",
    ["project_id"],
)


# Project scoped resource access
PROJECT_RESOURCE_ACCESS_TOTAL = Counter(
    "bess_project_resource_access_total",
    "Total project-scoped resource access",
    ["resource_type", "operation", "result"],  # resource_type: run, job, report; operation: read, write; result: allowed, denied
)


# Histogram for membership changes per project
PROJECT_MEMBERSHIP_CHANGES_HISTOGRAM = Histogram(
    "bess_project_membership_changes",
    "Distribution of membership change counts",
    ["operation"],  # add, update, remove
    buckets=[1, 2, 5, 10, 20, 50, 100],
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def record_project_operation(operation: str, success: bool):
    """Record a project CRUD operation.

    Args:
        operation: "create", "update", "archive", or "list"
        success: Whether the operation succeeded
    """
    PROJECT_OPERATIONS_TOTAL.labels(
        operation=operation,
        result="success" if success else "failure",
    ).inc()


def record_membership_operation(operation: str, role: str, success: bool):
    """Record a project membership operation.

    Args:
        operation: "add", "update", or "remove"
        role: "owner", "editor", or "viewer"
        success: Whether the operation succeeded
    """
    PROJECT_MEMBERSHIP_OPERATIONS_TOTAL.labels(
        operation=operation,
        role=role,
        result="success" if success else "failure",
    ).inc()


def record_project_access_check(required_role: str, allowed: bool):
    """Record a project access permission check.

    Args:
        required_role: The role that was required ("owner", "editor", "viewer")
        allowed: Whether access was allowed
    """
    PROJECT_ACCESS_CHECKS_TOTAL.labels(
        required_role=required_role,
        result="allowed" if allowed else "denied",
    ).inc()


def record_project_access_denied(reason: str):
    """Record a project access denial (for forbidden spike alerting).

    Args:
        reason: "not_member", "insufficient_role", "project_archived", "project_not_found"
    """
    PROJECT_ACCESS_DENIED_TOTAL.labels(reason=reason).inc()


def record_share_policy_enforcement(policy: str, result: str):
    """Record a share policy enforcement.

    Args:
        policy: "allow_public_shares" or "share_max_expiry"
        result: "allowed", "denied", or "clamped"
    """
    PROJECT_SHARE_POLICY_ENFORCEMENTS_TOTAL.labels(
        policy=policy,
        enforcement_result=result,
    ).inc()


def set_project_count(tenant_id: str, count: int):
    """Set the project count gauge for a tenant.

    Args:
        tenant_id: The tenant identifier
        count: Number of projects
    """
    PROJECT_COUNT.labels(tenant_id=tenant_id).set(count)


def set_membership_count(project_id: str, count: int):
    """Set the membership count gauge for a project.

    Args:
        project_id: The project identifier
        count: Number of members
    """
    PROJECT_MEMBERSHIP_COUNT.labels(project_id=project_id).set(count)


def record_project_resource_access(resource_type: str, operation: str, allowed: bool):
    """Record a project-scoped resource access attempt.

    Args:
        resource_type: "run", "job", or "report"
        operation: "read" or "write"
        allowed: Whether access was allowed
    """
    PROJECT_RESOURCE_ACCESS_TOTAL.labels(
        resource_type=resource_type,
        operation=operation,
        result="allowed" if allowed else "denied",
    ).inc()


def observe_membership_changes(operation: str, count: int):
    """Observe membership change count for histogram.

    Args:
        operation: "add", "update", or "remove"
        count: Number of members affected
    """
    PROJECT_MEMBERSHIP_CHANGES_HISTOGRAM.labels(operation=operation).observe(count)
