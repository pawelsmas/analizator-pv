"""
Compliance and retention metrics for Prometheus instrumentation (v4.3.0).

Provides:
- bess_retention_policy_operations_total: Counter for retention policy operations
- bess_legal_hold_operations_total: Counter for legal hold operations
- bess_legal_hold_active: Gauge for active legal holds count
- bess_purge_runs_total: Counter for purge runs (dry_run/execute)
- bess_purge_deleted_total: Counter for resources deleted
- bess_purge_skipped_total: Counter for resources skipped (held/error)
- bess_purge_duration_seconds: Histogram for purge duration
- bess_compliance_export_operations_total: Counter for export operations
- bess_compliance_export_size_bytes: Histogram for export bundle sizes
- bess_compliance_export_duration_seconds: Histogram for export duration

Label cardinality rules:
- result: "success" or "failure"
- mode: "dry_run" or "execute"
- category: resource category (runs, jobs, reports, etc.)
- reason: skip reason (held, error)
- operation: operation type (create, update, delete, etc.)
"""

from prometheus_client import Counter, Gauge, Histogram

SERVICE_NAME = "bess"

# Retention policy metrics
RETENTION_POLICY_OPERATIONS_TOTAL = Counter(
    "bess_retention_policy_operations_total",
    "Total retention policy operations",
    ["operation", "scope", "result"],  # operation: create, update, delete; scope: tenant, project; result: success, failure
)

RETENTION_POLICY_DAYS = Gauge(
    "bess_retention_policy_days",
    "Retention period in days by category",
    ["tenant_id", "category"],  # category: runs, jobs, reports, audit_logs, exports
)

# Legal hold metrics
LEGAL_HOLD_OPERATIONS_TOTAL = Counter(
    "bess_legal_hold_operations_total",
    "Total legal hold operations",
    ["operation", "resource_type", "result"],  # operation: create, release; resource_type: project, run, job, all
)

LEGAL_HOLD_ACTIVE = Gauge(
    "bess_legal_hold_active",
    "Number of active legal holds",
    ["tenant_id", "resource_type"],  # resource_type: project, run, job, all
)

LEGAL_HOLD_CHECKS_TOTAL = Counter(
    "bess_legal_hold_checks_total",
    "Total legal hold checks",
    ["result"],  # result: held, not_held
)

# Purge metrics
PURGE_RUNS_TOTAL = Counter(
    "bess_purge_runs_total",
    "Total purge runs",
    ["mode", "result"],  # mode: dry_run, execute; result: success, failure
)

PURGE_FOUND_TOTAL = Counter(
    "bess_purge_found_total",
    "Total resources found for deletion",
    ["category"],  # category: runs, jobs, reports, etc.
)

PURGE_DELETED_TOTAL = Counter(
    "bess_purge_deleted_total",
    "Total resources deleted",
    ["category"],  # category: runs, jobs, reports, etc.
)

PURGE_SKIPPED_TOTAL = Counter(
    "bess_purge_skipped_total",
    "Total resources skipped during purge",
    ["category", "reason"],  # category: runs, jobs, etc.; reason: held, error
)

PURGE_DURATION_SECONDS = Histogram(
    "bess_purge_duration_seconds",
    "Purge execution duration in seconds",
    ["mode"],  # mode: dry_run, execute
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

PURGE_HIT_LIMIT_TOTAL = Counter(
    "bess_purge_hit_limit_total",
    "Total purge runs that hit deletion limit",
    ["mode"],  # mode: dry_run, execute
)

# Compliance export metrics
COMPLIANCE_EXPORT_OPERATIONS_TOTAL = Counter(
    "bess_compliance_export_operations_total",
    "Total compliance export operations",
    ["operation", "result"],  # operation: create, download, delete; result: success, failure
)

COMPLIANCE_EXPORT_STATUS = Gauge(
    "bess_compliance_export_jobs",
    "Number of compliance export jobs by status",
    ["tenant_id", "status"],  # status: pending, running, completed, failed, expired
)

COMPLIANCE_EXPORT_SIZE_BYTES = Histogram(
    "bess_compliance_export_size_bytes",
    "Compliance export bundle size in bytes",
    [],
    buckets=[1024, 10240, 102400, 1048576, 10485760, 104857600, 1073741824],  # 1KB to 1GB
)

COMPLIANCE_EXPORT_RECORDS = Histogram(
    "bess_compliance_export_records",
    "Number of records in compliance export",
    [],
    buckets=[10, 100, 1000, 10000, 100000, 1000000],
)

COMPLIANCE_EXPORT_DURATION_SECONDS = Histogram(
    "bess_compliance_export_duration_seconds",
    "Compliance export generation duration in seconds",
    [],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0],
)


# Helper functions for recording metrics
def record_retention_policy_operation(operation: str, scope: str, success: bool):
    """Record a retention policy operation.

    Args:
        operation: "create", "update", or "delete"
        scope: "tenant" or "project"
        success: Whether the operation succeeded
    """
    RETENTION_POLICY_OPERATIONS_TOTAL.labels(
        operation=operation,
        scope=scope,
        result="success" if success else "failure",
    ).inc()


def update_retention_policy_days(tenant_id: str, category: str, days: int):
    """Update the retention days gauge for a category.

    Args:
        tenant_id: Tenant ID
        category: Resource category (runs, jobs, reports, etc.)
        days: Retention period in days (0 = indefinite, -1 = inherit)
    """
    RETENTION_POLICY_DAYS.labels(tenant_id=tenant_id, category=category).set(days)


def record_legal_hold_operation(operation: str, resource_type: str, success: bool):
    """Record a legal hold operation.

    Args:
        operation: "create" or "release"
        resource_type: "project", "run", "job", or "all"
        success: Whether the operation succeeded
    """
    LEGAL_HOLD_OPERATIONS_TOTAL.labels(
        operation=operation,
        resource_type=resource_type,
        result="success" if success else "failure",
    ).inc()


def update_legal_hold_count(tenant_id: str, resource_type: str, count: int):
    """Update the active legal hold count gauge.

    Args:
        tenant_id: Tenant ID
        resource_type: Resource type
        count: Number of active holds
    """
    LEGAL_HOLD_ACTIVE.labels(tenant_id=tenant_id, resource_type=resource_type).set(count)


def record_legal_hold_check(is_held: bool):
    """Record a legal hold check.

    Args:
        is_held: Whether the resource was held
    """
    LEGAL_HOLD_CHECKS_TOTAL.labels(result="held" if is_held else "not_held").inc()


def record_purge_run(mode: str, success: bool, duration_seconds: float):
    """Record a purge run.

    Args:
        mode: "dry_run" or "execute"
        success: Whether the purge succeeded
        duration_seconds: Duration of the purge
    """
    PURGE_RUNS_TOTAL.labels(mode=mode, result="success" if success else "failure").inc()
    PURGE_DURATION_SECONDS.labels(mode=mode).observe(duration_seconds)


def record_purge_found(category: str, count: int):
    """Record resources found for deletion.

    Args:
        category: Resource category
        count: Number of resources found
    """
    PURGE_FOUND_TOTAL.labels(category=category).inc(count)


def record_purge_deleted(category: str, count: int):
    """Record resources deleted.

    Args:
        category: Resource category
        count: Number of resources deleted
    """
    PURGE_DELETED_TOTAL.labels(category=category).inc(count)


def record_purge_skipped(category: str, reason: str, count: int):
    """Record resources skipped during purge.

    Args:
        category: Resource category
        reason: Skip reason ("held" or "error")
        count: Number of resources skipped
    """
    PURGE_SKIPPED_TOTAL.labels(category=category, reason=reason).inc(count)


def record_purge_hit_limit(mode: str):
    """Record that a purge run hit the deletion limit.

    Args:
        mode: "dry_run" or "execute"
    """
    PURGE_HIT_LIMIT_TOTAL.labels(mode=mode).inc()


def record_compliance_export_operation(operation: str, success: bool):
    """Record a compliance export operation.

    Args:
        operation: "create", "download", or "delete"
        success: Whether the operation succeeded
    """
    COMPLIANCE_EXPORT_OPERATIONS_TOTAL.labels(
        operation=operation,
        result="success" if success else "failure",
    ).inc()


def update_compliance_export_status(tenant_id: str, status: str, count: int):
    """Update the compliance export job count by status.

    Args:
        tenant_id: Tenant ID
        status: Job status
        count: Number of jobs in this status
    """
    COMPLIANCE_EXPORT_STATUS.labels(tenant_id=tenant_id, status=status).set(count)


def record_compliance_export_size(size_bytes: int):
    """Record the size of a compliance export bundle.

    Args:
        size_bytes: Size in bytes
    """
    COMPLIANCE_EXPORT_SIZE_BYTES.observe(size_bytes)


def record_compliance_export_records(record_count: int):
    """Record the number of records in a compliance export.

    Args:
        record_count: Number of records
    """
    COMPLIANCE_EXPORT_RECORDS.observe(record_count)


def record_compliance_export_duration(duration_seconds: float):
    """Record the duration of a compliance export generation.

    Args:
        duration_seconds: Duration in seconds
    """
    COMPLIANCE_EXPORT_DURATION_SECONDS.observe(duration_seconds)
