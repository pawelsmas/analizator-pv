"""
Unit tests for db_metrics.py (v3.3.0 PR6).

Tests database observability metrics for Prometheus.
"""

import pytest
import os
import sys

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestDbMetricsImports:
    """Tests for db_metrics imports."""

    def test_import_db_metrics(self):
        """db_metrics should be importable."""
        import observability.db_metrics as db_metrics
        assert db_metrics is not None

    def test_all_counters_importable(self):
        """All counter metrics should be importable."""
        from observability.db_metrics import (
            DB_HEALTH_CHECK_TOTAL,
            DB_MIGRATION_RUNS_TOTAL,
            DB_BACKFILL_RECORDS_TOTAL,
            DB_BACKUP_OPERATIONS_TOTAL,
            DB_RESTORE_OPERATIONS_TOTAL,
            DB_RETENTION_CLEANUP_TOTAL,
            DB_RETENTION_DELETED_TOTAL,
            DB_TRANSACTION_TOTAL,
            DB_ROW_OPERATIONS_TOTAL,
        )
        assert DB_HEALTH_CHECK_TOTAL is not None
        assert DB_MIGRATION_RUNS_TOTAL is not None
        assert DB_BACKFILL_RECORDS_TOTAL is not None
        assert DB_BACKUP_OPERATIONS_TOTAL is not None
        assert DB_RESTORE_OPERATIONS_TOTAL is not None
        assert DB_RETENTION_CLEANUP_TOTAL is not None
        assert DB_RETENTION_DELETED_TOTAL is not None
        assert DB_TRANSACTION_TOTAL is not None
        assert DB_ROW_OPERATIONS_TOTAL is not None

    def test_all_histograms_importable(self):
        """All histogram metrics should be importable."""
        from observability.db_metrics import (
            DB_HEALTH_CHECK_LATENCY,
            DB_MIGRATION_DURATION,
            DB_BACKFILL_DURATION,
            DB_BACKUP_SIZE_BYTES,
            DB_BACKUP_DURATION,
            DB_RESTORE_DURATION,
        )
        assert DB_HEALTH_CHECK_LATENCY is not None
        assert DB_MIGRATION_DURATION is not None
        assert DB_BACKFILL_DURATION is not None
        assert DB_BACKUP_SIZE_BYTES is not None
        assert DB_BACKUP_DURATION is not None
        assert DB_RESTORE_DURATION is not None

    def test_all_gauges_importable(self):
        """All gauge metrics should be importable."""
        from observability.db_metrics import (
            DB_POOL_SIZE,
            DB_POOL_OVERFLOW,
            DB_POOL_CHECKEDOUT,
            DB_POOL_CHECKEDIN,
        )
        assert DB_POOL_SIZE is not None
        assert DB_POOL_OVERFLOW is not None
        assert DB_POOL_CHECKEDOUT is not None
        assert DB_POOL_CHECKEDIN is not None

    def test_info_metric_importable(self):
        """Info metric should be importable."""
        from observability.db_metrics import DB_BACKEND_INFO
        assert DB_BACKEND_INFO is not None


class TestDbMetricsHelperFunctions:
    """Tests for db_metrics helper functions."""

    def test_record_health_check_success(self):
        """record_health_check should record successful health check."""
        from observability.db_metrics import record_health_check, DB_HEALTH_CHECK_TOTAL

        # Get initial value
        initial = DB_HEALTH_CHECK_TOTAL.labels(result="ok")._value.get()

        record_health_check(ok=True, latency_seconds=0.005)

        # Value should have increased
        assert DB_HEALTH_CHECK_TOTAL.labels(result="ok")._value.get() == initial + 1

    def test_record_health_check_failure(self):
        """record_health_check should record failed health check."""
        from observability.db_metrics import record_health_check, DB_HEALTH_CHECK_TOTAL

        initial = DB_HEALTH_CHECK_TOTAL.labels(result="error")._value.get()

        record_health_check(ok=False, latency_seconds=0.100)

        assert DB_HEALTH_CHECK_TOTAL.labels(result="error")._value.get() == initial + 1

    def test_record_migration_up_success(self):
        """record_migration should record successful upgrade."""
        from observability.db_metrics import record_migration, DB_MIGRATION_RUNS_TOTAL

        initial = DB_MIGRATION_RUNS_TOTAL.labels(direction="up", result="success")._value.get()

        record_migration(direction="up", success=True, duration_seconds=1.5)

        assert DB_MIGRATION_RUNS_TOTAL.labels(direction="up", result="success")._value.get() == initial + 1

    def test_record_migration_down_failure(self):
        """record_migration should record failed downgrade."""
        from observability.db_metrics import record_migration, DB_MIGRATION_RUNS_TOTAL

        initial = DB_MIGRATION_RUNS_TOTAL.labels(direction="down", result="failure")._value.get()

        record_migration(direction="down", success=False)

        assert DB_MIGRATION_RUNS_TOTAL.labels(direction="down", result="failure")._value.get() == initial + 1

    def test_record_backfill_inserted(self):
        """record_backfill should record inserted records."""
        from observability.db_metrics import record_backfill, DB_BACKFILL_RECORDS_TOTAL

        initial = DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="inserted")._value.get()

        record_backfill(table="run_index", result="inserted", count=10)

        assert DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="inserted")._value.get() == initial + 10

    def test_record_backfill_skipped(self):
        """record_backfill should record skipped records."""
        from observability.db_metrics import record_backfill, DB_BACKFILL_RECORDS_TOTAL

        initial = DB_BACKFILL_RECORDS_TOTAL.labels(table="job_index", result="skipped")._value.get()

        record_backfill(table="job_index", result="skipped", count=5)

        assert DB_BACKFILL_RECORDS_TOTAL.labels(table="job_index", result="skipped")._value.get() == initial + 5

    def test_record_backup_success(self):
        """record_backup should record successful backup."""
        from observability.db_metrics import record_backup, DB_BACKUP_OPERATIONS_TOTAL

        initial = DB_BACKUP_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get()

        record_backup(format="custom", success=True, size_bytes=1024*1024, duration_seconds=5.0)

        assert DB_BACKUP_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get() == initial + 1

    def test_record_backup_failure(self):
        """record_backup should record failed backup."""
        from observability.db_metrics import record_backup, DB_BACKUP_OPERATIONS_TOTAL

        initial = DB_BACKUP_OPERATIONS_TOTAL.labels(format="plain", result="failure")._value.get()

        record_backup(format="plain", success=False)

        assert DB_BACKUP_OPERATIONS_TOTAL.labels(format="plain", result="failure")._value.get() == initial + 1

    def test_record_restore_success(self):
        """record_restore should record successful restore."""
        from observability.db_metrics import record_restore, DB_RESTORE_OPERATIONS_TOTAL

        initial = DB_RESTORE_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get()

        record_restore(format="custom", success=True, duration_seconds=10.0)

        assert DB_RESTORE_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get() == initial + 1

    def test_record_restore_failure(self):
        """record_restore should record failed restore."""
        from observability.db_metrics import record_restore, DB_RESTORE_OPERATIONS_TOTAL

        initial = DB_RESTORE_OPERATIONS_TOTAL.labels(format="sql", result="failure")._value.get()

        record_restore(format="sql", success=False)

        assert DB_RESTORE_OPERATIONS_TOTAL.labels(format="sql", result="failure")._value.get() == initial + 1

    def test_record_retention_cleanup_success(self):
        """record_retention_cleanup should record successful cleanup."""
        from observability.db_metrics import record_retention_cleanup, DB_RETENTION_CLEANUP_TOTAL

        initial = DB_RETENTION_CLEANUP_TOTAL.labels(store="runs", result="success")._value.get()

        record_retention_cleanup(store="runs", success=True, deleted_count=50)

        assert DB_RETENTION_CLEANUP_TOTAL.labels(store="runs", result="success")._value.get() == initial + 1

    def test_record_retention_cleanup_failure(self):
        """record_retention_cleanup should record failed cleanup."""
        from observability.db_metrics import record_retention_cleanup, DB_RETENTION_CLEANUP_TOTAL

        initial = DB_RETENTION_CLEANUP_TOTAL.labels(store="jobs", result="failure")._value.get()

        record_retention_cleanup(store="jobs", success=False)

        assert DB_RETENTION_CLEANUP_TOTAL.labels(store="jobs", result="failure")._value.get() == initial + 1

    def test_record_transaction_success(self):
        """record_transaction should record successful transaction."""
        from observability.db_metrics import record_transaction, DB_TRANSACTION_TOTAL

        initial = DB_TRANSACTION_TOTAL.labels(result="success")._value.get()

        record_transaction(result="success")

        assert DB_TRANSACTION_TOTAL.labels(result="success")._value.get() == initial + 1

    def test_record_transaction_rollback(self):
        """record_transaction should record rollback."""
        from observability.db_metrics import record_transaction, DB_TRANSACTION_TOTAL

        initial = DB_TRANSACTION_TOTAL.labels(result="rollback")._value.get()

        record_transaction(result="rollback")

        assert DB_TRANSACTION_TOTAL.labels(result="rollback")._value.get() == initial + 1

    def test_record_row_operation_insert(self):
        """record_row_operation should record insert."""
        from observability.db_metrics import record_row_operation, DB_ROW_OPERATIONS_TOTAL

        initial = DB_ROW_OPERATIONS_TOTAL.labels(table="runs", operation="insert")._value.get()

        record_row_operation(table="runs", operation="insert", count=5)

        assert DB_ROW_OPERATIONS_TOTAL.labels(table="runs", operation="insert")._value.get() == initial + 5

    def test_record_row_operation_delete(self):
        """record_row_operation should record delete."""
        from observability.db_metrics import record_row_operation, DB_ROW_OPERATIONS_TOTAL

        initial = DB_ROW_OPERATIONS_TOTAL.labels(table="audit", operation="delete")._value.get()

        record_row_operation(table="audit", operation="delete", count=100)

        assert DB_ROW_OPERATIONS_TOTAL.labels(table="audit", operation="delete")._value.get() == initial + 100

    def test_update_pool_metrics(self):
        """update_pool_metrics should set all pool gauges."""
        from observability.db_metrics import (
            update_pool_metrics,
            DB_POOL_SIZE,
            DB_POOL_OVERFLOW,
            DB_POOL_CHECKEDOUT,
            DB_POOL_CHECKEDIN,
        )

        update_pool_metrics(pool_size=5, overflow=2, checkedout=3, checkedin=4)

        assert DB_POOL_SIZE._value.get() == 5
        assert DB_POOL_OVERFLOW._value.get() == 2
        assert DB_POOL_CHECKEDOUT._value.get() == 3
        assert DB_POOL_CHECKEDIN._value.get() == 4

    def test_set_backend_info(self):
        """set_backend_info should set info metric."""
        from observability.db_metrics import set_backend_info, DB_BACKEND_INFO

        set_backend_info(backend="postgres", version="15.2", migrations_current=True)

        # Info metrics store values differently, just verify no exception


class TestDbMetricsLabels:
    """Tests for metric label values."""

    def test_health_check_result_labels(self):
        """Health check should support ok and error results."""
        from observability.db_metrics import DB_HEALTH_CHECK_TOTAL

        # Should not raise
        DB_HEALTH_CHECK_TOTAL.labels(result="ok")
        DB_HEALTH_CHECK_TOTAL.labels(result="error")

    def test_migration_direction_labels(self):
        """Migration should support up and down directions."""
        from observability.db_metrics import DB_MIGRATION_RUNS_TOTAL

        # Should not raise
        DB_MIGRATION_RUNS_TOTAL.labels(direction="up", result="success")
        DB_MIGRATION_RUNS_TOTAL.labels(direction="down", result="failure")

    def test_backfill_table_labels(self):
        """Backfill should support run_index and job_index tables."""
        from observability.db_metrics import DB_BACKFILL_RECORDS_TOTAL

        # Should not raise
        DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="inserted")
        DB_BACKFILL_RECORDS_TOTAL.labels(table="job_index", result="skipped")
        DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="error")

    def test_backup_format_labels(self):
        """Backup should support all pg_dump formats."""
        from observability.db_metrics import DB_BACKUP_OPERATIONS_TOTAL

        # Should not raise
        DB_BACKUP_OPERATIONS_TOTAL.labels(format="custom", result="success")
        DB_BACKUP_OPERATIONS_TOTAL.labels(format="plain", result="success")
        DB_BACKUP_OPERATIONS_TOTAL.labels(format="directory", result="success")
        DB_BACKUP_OPERATIONS_TOTAL.labels(format="tar", result="success")

    def test_retention_store_labels(self):
        """Retention cleanup should support all store types."""
        from observability.db_metrics import DB_RETENTION_CLEANUP_TOTAL

        # Should not raise
        DB_RETENTION_CLEANUP_TOTAL.labels(store="runs", result="success")
        DB_RETENTION_CLEANUP_TOTAL.labels(store="jobs", result="success")
        DB_RETENTION_CLEANUP_TOTAL.labels(store="audit", result="success")
        DB_RETENTION_CLEANUP_TOTAL.labels(store="backups", result="success")

    def test_transaction_result_labels(self):
        """Transaction should support success, rollback, error."""
        from observability.db_metrics import DB_TRANSACTION_TOTAL

        # Should not raise
        DB_TRANSACTION_TOTAL.labels(result="success")
        DB_TRANSACTION_TOTAL.labels(result="rollback")
        DB_TRANSACTION_TOTAL.labels(result="error")

    def test_row_operation_labels(self):
        """Row operations should support insert, update, delete."""
        from observability.db_metrics import DB_ROW_OPERATIONS_TOTAL

        # Should not raise
        DB_ROW_OPERATIONS_TOTAL.labels(table="runs", operation="insert")
        DB_ROW_OPERATIONS_TOTAL.labels(table="jobs", operation="update")
        DB_ROW_OPERATIONS_TOTAL.labels(table="audit", operation="delete")


class TestDbMetricsHistogramBuckets:
    """Tests for histogram bucket configurations."""

    def test_health_check_latency_buckets(self):
        """Health check latency should have sub-second buckets."""
        from observability.db_metrics import DB_HEALTH_CHECK_LATENCY

        # Access the buckets (they're on the underlying metric)
        buckets = list(DB_HEALTH_CHECK_LATENCY._kwargs.get('buckets', []))

        # Should have buckets for fast health checks
        assert 0.001 in buckets  # 1ms
        assert 0.01 in buckets   # 10ms
        assert 0.1 in buckets    # 100ms

    def test_migration_duration_buckets(self):
        """Migration duration should have up to 60s buckets."""
        from observability.db_metrics import DB_MIGRATION_DURATION

        buckets = list(DB_MIGRATION_DURATION._kwargs.get('buckets', []))

        # Should have buckets for slow migrations
        assert 1.0 in buckets
        assert 10.0 in buckets
        assert 60.0 in buckets

    def test_backup_size_buckets(self):
        """Backup size should have MB to GB buckets."""
        from observability.db_metrics import DB_BACKUP_SIZE_BYTES

        buckets = list(DB_BACKUP_SIZE_BYTES._kwargs.get('buckets', []))

        # Should have buckets for large backups
        assert 1e6 in buckets   # 1MB
        assert 100e6 in buckets # 100MB
        assert 1e9 in buckets   # 1GB
