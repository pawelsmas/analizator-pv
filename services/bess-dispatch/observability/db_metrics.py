"""
Database observability metrics for Prometheus instrumentation (v3.3.0 PR6).

Provides comprehensive metrics for database operations:
- bess_db_query_duration_seconds: Histogram for query latency (already in db_config.py)
- bess_db_errors_total: Counter for errors by code (already in db_config.py)
- bess_db_connections_open: Gauge for open connections (already in db_config.py)
- bess_db_migrations_pending: Gauge for pending migrations (already in db_config.py)

Additional metrics added here:
- bess_db_pool_size: Gauge for connection pool size
- bess_db_pool_overflow: Gauge for pool overflow count
- bess_db_pool_checkedout: Gauge for checked out connections
- bess_db_health_check_total: Counter for health check requests
- bess_db_health_check_latency_seconds: Histogram for health check latency
- bess_db_backfill_records_total: Counter for backfill operations
- bess_db_backup_operations_total: Counter for backup operations
- bess_db_restore_operations_total: Counter for restore operations
- bess_db_retention_cleanup_total: Counter for retention cleanup
- bess_db_transaction_total: Counter for transactions by result
- bess_db_row_operations_total: Counter for row operations (insert/update/delete)
"""

from prometheus_client import Counter, Histogram, Gauge, Info

SERVICE_NAME = "bess"


# Connection pool metrics
DB_POOL_SIZE = Gauge(
    "bess_db_pool_size",
    "Database connection pool size",
)

DB_POOL_OVERFLOW = Gauge(
    "bess_db_pool_overflow",
    "Database connection pool overflow count",
)

DB_POOL_CHECKEDOUT = Gauge(
    "bess_db_pool_checkedout",
    "Database connections currently checked out",
)

DB_POOL_CHECKEDIN = Gauge(
    "bess_db_pool_checkedin",
    "Database connections currently checked in",
)


# Health check metrics
DB_HEALTH_CHECK_TOTAL = Counter(
    "bess_db_health_check_total",
    "Total database health check requests",
    ["result"],  # ok, error
)

DB_HEALTH_CHECK_LATENCY = Histogram(
    "bess_db_health_check_latency_seconds",
    "Database health check latency in seconds",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)


# Migration metrics
DB_MIGRATION_RUNS_TOTAL = Counter(
    "bess_db_migration_runs_total",
    "Total migration runs",
    ["direction", "result"],  # direction: up, down; result: success, failure
)

DB_MIGRATION_DURATION = Histogram(
    "bess_db_migration_duration_seconds",
    "Database migration duration in seconds",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)


# Backfill metrics
DB_BACKFILL_RECORDS_TOTAL = Counter(
    "bess_db_backfill_records_total",
    "Total records backfilled",
    ["table", "result"],  # table: run_index, job_index; result: inserted, skipped, error
)

DB_BACKFILL_DURATION = Histogram(
    "bess_db_backfill_duration_seconds",
    "Database backfill duration in seconds",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)


# Backup/restore metrics
DB_BACKUP_OPERATIONS_TOTAL = Counter(
    "bess_db_backup_operations_total",
    "Total backup operations",
    ["format", "result"],  # format: custom, plain, directory, tar; result: success, failure
)

DB_BACKUP_SIZE_BYTES = Histogram(
    "bess_db_backup_size_bytes",
    "Backup file size in bytes",
    buckets=[1e6, 10e6, 100e6, 500e6, 1e9, 5e9],  # 1MB to 5GB
)

DB_BACKUP_DURATION = Histogram(
    "bess_db_backup_duration_seconds",
    "Backup operation duration in seconds",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

DB_RESTORE_OPERATIONS_TOTAL = Counter(
    "bess_db_restore_operations_total",
    "Total restore operations",
    ["format", "result"],  # format: custom, plain, sql; result: success, failure
)

DB_RESTORE_DURATION = Histogram(
    "bess_db_restore_duration_seconds",
    "Restore operation duration in seconds",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)


# Retention cleanup metrics
DB_RETENTION_CLEANUP_TOTAL = Counter(
    "bess_db_retention_cleanup_total",
    "Total retention cleanup operations",
    ["store", "result"],  # store: runs, jobs, audit, backups; result: success, failure
)

DB_RETENTION_DELETED_TOTAL = Counter(
    "bess_db_retention_deleted_total",
    "Total records deleted by retention cleanup",
    ["store"],  # store: runs, jobs, audit, backups
)


# Transaction metrics
DB_TRANSACTION_TOTAL = Counter(
    "bess_db_transaction_total",
    "Total database transactions",
    ["result"],  # success, rollback, error
)


# Row operation metrics
DB_ROW_OPERATIONS_TOTAL = Counter(
    "bess_db_row_operations_total",
    "Total row operations",
    ["table", "operation"],  # table: runs, jobs, etc; operation: insert, update, delete
)


# Backend info
DB_BACKEND_INFO = Info(
    "bess_db_backend",
    "Database backend information",
)


# Helper functions for recording metrics
def record_health_check(ok: bool, latency_seconds: float):
    """Record a database health check result."""
    DB_HEALTH_CHECK_TOTAL.labels(result="ok" if ok else "error").inc()
    DB_HEALTH_CHECK_LATENCY.observe(latency_seconds)


def record_migration(direction: str, success: bool, duration_seconds: float = 0):
    """Record a migration run.

    Args:
        direction: "up" or "down"
        success: Whether the migration succeeded
        duration_seconds: Duration of the migration
    """
    DB_MIGRATION_RUNS_TOTAL.labels(
        direction=direction,
        result="success" if success else "failure",
    ).inc()
    if duration_seconds > 0:
        DB_MIGRATION_DURATION.observe(duration_seconds)


def record_backfill(table: str, result: str, count: int = 1, duration_seconds: float = 0):
    """Record backfill records.

    Args:
        table: "run_index" or "job_index"
        result: "inserted", "skipped", or "error"
        count: Number of records
        duration_seconds: Total duration if completed
    """
    DB_BACKFILL_RECORDS_TOTAL.labels(table=table, result=result).inc(count)
    if duration_seconds > 0:
        DB_BACKFILL_DURATION.observe(duration_seconds)


def record_backup(format: str, success: bool, size_bytes: int = 0, duration_seconds: float = 0):
    """Record a backup operation.

    Args:
        format: "custom", "plain", "directory", or "tar"
        success: Whether the backup succeeded
        size_bytes: Size of the backup file
        duration_seconds: Duration of the backup
    """
    DB_BACKUP_OPERATIONS_TOTAL.labels(
        format=format,
        result="success" if success else "failure",
    ).inc()
    if size_bytes > 0:
        DB_BACKUP_SIZE_BYTES.observe(size_bytes)
    if duration_seconds > 0:
        DB_BACKUP_DURATION.observe(duration_seconds)


def record_restore(format: str, success: bool, duration_seconds: float = 0):
    """Record a restore operation.

    Args:
        format: "custom", "plain", or "sql"
        success: Whether the restore succeeded
        duration_seconds: Duration of the restore
    """
    DB_RESTORE_OPERATIONS_TOTAL.labels(
        format=format,
        result="success" if success else "failure",
    ).inc()
    if duration_seconds > 0:
        DB_RESTORE_DURATION.observe(duration_seconds)


def record_retention_cleanup(store: str, success: bool, deleted_count: int = 0):
    """Record a retention cleanup operation.

    Args:
        store: "runs", "jobs", "audit", or "backups"
        success: Whether the cleanup succeeded
        deleted_count: Number of records deleted
    """
    DB_RETENTION_CLEANUP_TOTAL.labels(
        store=store,
        result="success" if success else "failure",
    ).inc()
    if deleted_count > 0:
        DB_RETENTION_DELETED_TOTAL.labels(store=store).inc(deleted_count)


def record_transaction(result: str):
    """Record a database transaction.

    Args:
        result: "success", "rollback", or "error"
    """
    DB_TRANSACTION_TOTAL.labels(result=result).inc()


def record_row_operation(table: str, operation: str, count: int = 1):
    """Record row operations.

    Args:
        table: Table name
        operation: "insert", "update", or "delete"
        count: Number of rows affected
    """
    DB_ROW_OPERATIONS_TOTAL.labels(table=table, operation=operation).inc(count)


def update_pool_metrics(pool_size: int, overflow: int, checkedout: int, checkedin: int):
    """Update connection pool metrics.

    Args:
        pool_size: Current pool size
        overflow: Current overflow count
        checkedout: Connections checked out
        checkedin: Connections checked in
    """
    DB_POOL_SIZE.set(pool_size)
    DB_POOL_OVERFLOW.set(overflow)
    DB_POOL_CHECKEDOUT.set(checkedout)
    DB_POOL_CHECKEDIN.set(checkedin)


def set_backend_info(backend: str, version: str = "", migrations_current: bool = True):
    """Set database backend information.

    Args:
        backend: "sqlite" or "postgres"
        version: Database version string
        migrations_current: Whether migrations are current
    """
    DB_BACKEND_INFO.info({
        "backend": backend,
        "version": version,
        "migrations_current": "true" if migrations_current else "false",
    })
