"""
Contract tests for database observability metrics (v3.3.0 PR6).

Tests that all required metrics are present and correctly configured.
"""

import pytest
import os
import sys

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestDbConfigMetrics:
    """Tests for metrics defined in db_config.py."""

    def test_db_query_duration_exists(self):
        """DB_QUERY_DURATION histogram should exist."""
        from db_config import DB_QUERY_DURATION

        assert DB_QUERY_DURATION is not None
        assert DB_QUERY_DURATION._name == "bess_db_query_duration_seconds"

    def test_db_query_duration_labels(self):
        """DB_QUERY_DURATION should have repo and op labels."""
        from db_config import DB_QUERY_DURATION

        # Should work with these labels
        DB_QUERY_DURATION.labels(repo="auth_repo", op="get_user")
        DB_QUERY_DURATION.labels(repo="audit_repo", op="log")

    def test_db_errors_total_exists(self):
        """DB_ERRORS_TOTAL counter should exist."""
        from db_config import DB_ERRORS_TOTAL

        assert DB_ERRORS_TOTAL is not None
        # Counter metrics don't have _total in internal name (Prometheus adds it)
        assert "bess_db_errors" in DB_ERRORS_TOTAL._name

    def test_db_errors_total_labels(self):
        """DB_ERRORS_TOTAL should have code label."""
        from db_config import DB_ERRORS_TOTAL

        # Should work with code label
        DB_ERRORS_TOTAL.labels(code="connection_error")
        DB_ERRORS_TOTAL.labels(code="query_error")
        DB_ERRORS_TOTAL.labels(code="timeout")

    def test_db_connections_open_exists(self):
        """DB_CONNECTIONS_OPEN gauge should exist."""
        from db_config import DB_CONNECTIONS_OPEN

        assert DB_CONNECTIONS_OPEN is not None
        assert DB_CONNECTIONS_OPEN._name == "bess_db_connections_open"

    def test_db_migrations_pending_exists(self):
        """DB_MIGRATIONS_PENDING gauge should exist."""
        from db_config import DB_MIGRATIONS_PENDING

        assert DB_MIGRATIONS_PENDING is not None
        assert DB_MIGRATIONS_PENDING._name == "bess_db_migrations_pending"


class TestDbMetricsModule:
    """Tests for metrics defined in db_metrics.py."""

    def test_pool_metrics_exist(self):
        """Connection pool metrics should exist."""
        from observability.db_metrics import (
            DB_POOL_SIZE,
            DB_POOL_OVERFLOW,
            DB_POOL_CHECKEDOUT,
            DB_POOL_CHECKEDIN,
        )

        assert DB_POOL_SIZE._name == "bess_db_pool_size"
        assert DB_POOL_OVERFLOW._name == "bess_db_pool_overflow"
        assert DB_POOL_CHECKEDOUT._name == "bess_db_pool_checkedout"
        assert DB_POOL_CHECKEDIN._name == "bess_db_pool_checkedin"

    def test_health_check_metrics_exist(self):
        """Health check metrics should exist."""
        from observability.db_metrics import (
            DB_HEALTH_CHECK_TOTAL,
            DB_HEALTH_CHECK_LATENCY,
        )

        # Counter metrics don't have _total in internal name (Prometheus adds it)
        assert "bess_db_health_check" in DB_HEALTH_CHECK_TOTAL._name
        assert DB_HEALTH_CHECK_LATENCY._name == "bess_db_health_check_latency_seconds"

    def test_migration_metrics_exist(self):
        """Migration metrics should exist."""
        from observability.db_metrics import (
            DB_MIGRATION_RUNS_TOTAL,
            DB_MIGRATION_DURATION,
        )

        assert "bess_db_migration_runs" in DB_MIGRATION_RUNS_TOTAL._name
        assert DB_MIGRATION_DURATION._name == "bess_db_migration_duration_seconds"

    def test_backfill_metrics_exist(self):
        """Backfill metrics should exist."""
        from observability.db_metrics import (
            DB_BACKFILL_RECORDS_TOTAL,
            DB_BACKFILL_DURATION,
        )

        assert "bess_db_backfill_records" in DB_BACKFILL_RECORDS_TOTAL._name
        assert DB_BACKFILL_DURATION._name == "bess_db_backfill_duration_seconds"

    def test_backup_metrics_exist(self):
        """Backup metrics should exist."""
        from observability.db_metrics import (
            DB_BACKUP_OPERATIONS_TOTAL,
            DB_BACKUP_SIZE_BYTES,
            DB_BACKUP_DURATION,
        )

        assert "bess_db_backup_operations" in DB_BACKUP_OPERATIONS_TOTAL._name
        assert DB_BACKUP_SIZE_BYTES._name == "bess_db_backup_size_bytes"
        assert DB_BACKUP_DURATION._name == "bess_db_backup_duration_seconds"

    def test_restore_metrics_exist(self):
        """Restore metrics should exist."""
        from observability.db_metrics import (
            DB_RESTORE_OPERATIONS_TOTAL,
            DB_RESTORE_DURATION,
        )

        assert "bess_db_restore_operations" in DB_RESTORE_OPERATIONS_TOTAL._name
        assert DB_RESTORE_DURATION._name == "bess_db_restore_duration_seconds"

    def test_retention_metrics_exist(self):
        """Retention metrics should exist."""
        from observability.db_metrics import (
            DB_RETENTION_CLEANUP_TOTAL,
            DB_RETENTION_DELETED_TOTAL,
        )

        assert "bess_db_retention_cleanup" in DB_RETENTION_CLEANUP_TOTAL._name
        assert "bess_db_retention_deleted" in DB_RETENTION_DELETED_TOTAL._name

    def test_transaction_metrics_exist(self):
        """Transaction metrics should exist."""
        from observability.db_metrics import DB_TRANSACTION_TOTAL

        assert "bess_db_transaction" in DB_TRANSACTION_TOTAL._name

    def test_row_operations_metrics_exist(self):
        """Row operations metrics should exist."""
        from observability.db_metrics import DB_ROW_OPERATIONS_TOTAL

        assert "bess_db_row_operations" in DB_ROW_OPERATIONS_TOTAL._name

    def test_backend_info_exists(self):
        """Backend info metric should exist."""
        from observability.db_metrics import DB_BACKEND_INFO

        assert DB_BACKEND_INFO._name == "bess_db_backend"


class TestDbMetricsHelperFunctions:
    """Tests for helper function signatures."""

    def test_record_health_check_callable(self):
        """record_health_check should be callable with correct args."""
        from observability.db_metrics import record_health_check

        # Should not raise
        record_health_check(ok=True, latency_seconds=0.01)
        record_health_check(ok=False, latency_seconds=0.5)

    def test_record_migration_callable(self):
        """record_migration should be callable with correct args."""
        from observability.db_metrics import record_migration

        # Should not raise
        record_migration(direction="up", success=True)
        record_migration(direction="down", success=False, duration_seconds=2.0)

    def test_record_backfill_callable(self):
        """record_backfill should be callable with correct args."""
        from observability.db_metrics import record_backfill

        # Should not raise
        record_backfill(table="run_index", result="inserted")
        record_backfill(table="job_index", result="skipped", count=5)
        record_backfill(table="run_index", result="error", count=1, duration_seconds=10.0)

    def test_record_backup_callable(self):
        """record_backup should be callable with correct args."""
        from observability.db_metrics import record_backup

        # Should not raise
        record_backup(format="custom", success=True)
        record_backup(format="plain", success=False, size_bytes=1024, duration_seconds=5.0)

    def test_record_restore_callable(self):
        """record_restore should be callable with correct args."""
        from observability.db_metrics import record_restore

        # Should not raise
        record_restore(format="custom", success=True)
        record_restore(format="sql", success=False, duration_seconds=30.0)

    def test_record_retention_cleanup_callable(self):
        """record_retention_cleanup should be callable with correct args."""
        from observability.db_metrics import record_retention_cleanup

        # Should not raise
        record_retention_cleanup(store="runs", success=True)
        record_retention_cleanup(store="jobs", success=False, deleted_count=100)

    def test_record_transaction_callable(self):
        """record_transaction should be callable with correct args."""
        from observability.db_metrics import record_transaction

        # Should not raise
        record_transaction(result="success")
        record_transaction(result="rollback")
        record_transaction(result="error")

    def test_record_row_operation_callable(self):
        """record_row_operation should be callable with correct args."""
        from observability.db_metrics import record_row_operation

        # Should not raise
        record_row_operation(table="runs", operation="insert")
        record_row_operation(table="jobs", operation="update", count=10)
        record_row_operation(table="audit", operation="delete", count=50)

    def test_update_pool_metrics_callable(self):
        """update_pool_metrics should be callable with correct args."""
        from observability.db_metrics import update_pool_metrics

        # Should not raise
        update_pool_metrics(pool_size=5, overflow=0, checkedout=2, checkedin=3)

    def test_set_backend_info_callable(self):
        """set_backend_info should be callable with correct args."""
        from observability.db_metrics import set_backend_info

        # Should not raise
        set_backend_info(backend="sqlite")
        set_backend_info(backend="postgres", version="15.2")
        set_backend_info(backend="postgres", version="15.2", migrations_current=True)


class TestDbMetricsNaming:
    """Tests for metric naming conventions."""

    def test_all_metrics_have_bess_prefix(self):
        """All metrics should have bess_ prefix."""
        from observability.db_metrics import (
            DB_POOL_SIZE,
            DB_POOL_OVERFLOW,
            DB_POOL_CHECKEDOUT,
            DB_POOL_CHECKEDIN,
            DB_HEALTH_CHECK_TOTAL,
            DB_HEALTH_CHECK_LATENCY,
            DB_MIGRATION_RUNS_TOTAL,
            DB_MIGRATION_DURATION,
            DB_BACKFILL_RECORDS_TOTAL,
            DB_BACKFILL_DURATION,
            DB_BACKUP_OPERATIONS_TOTAL,
            DB_BACKUP_SIZE_BYTES,
            DB_BACKUP_DURATION,
            DB_RESTORE_OPERATIONS_TOTAL,
            DB_RESTORE_DURATION,
            DB_RETENTION_CLEANUP_TOTAL,
            DB_RETENTION_DELETED_TOTAL,
            DB_TRANSACTION_TOTAL,
            DB_ROW_OPERATIONS_TOTAL,
            DB_BACKEND_INFO,
        )

        metrics = [
            DB_POOL_SIZE,
            DB_POOL_OVERFLOW,
            DB_POOL_CHECKEDOUT,
            DB_POOL_CHECKEDIN,
            DB_HEALTH_CHECK_TOTAL,
            DB_HEALTH_CHECK_LATENCY,
            DB_MIGRATION_RUNS_TOTAL,
            DB_MIGRATION_DURATION,
            DB_BACKFILL_RECORDS_TOTAL,
            DB_BACKFILL_DURATION,
            DB_BACKUP_OPERATIONS_TOTAL,
            DB_BACKUP_SIZE_BYTES,
            DB_BACKUP_DURATION,
            DB_RESTORE_OPERATIONS_TOTAL,
            DB_RESTORE_DURATION,
            DB_RETENTION_CLEANUP_TOTAL,
            DB_RETENTION_DELETED_TOTAL,
            DB_TRANSACTION_TOTAL,
            DB_ROW_OPERATIONS_TOTAL,
            DB_BACKEND_INFO,
        ]

        for metric in metrics:
            assert metric._name.startswith("bess_"), f"{metric._name} should start with bess_"

    def test_all_metrics_have_db_prefix(self):
        """All db metrics should have bess_db_ prefix."""
        from observability.db_metrics import (
            DB_POOL_SIZE,
            DB_HEALTH_CHECK_TOTAL,
            DB_MIGRATION_RUNS_TOTAL,
            DB_BACKFILL_RECORDS_TOTAL,
            DB_BACKUP_OPERATIONS_TOTAL,
            DB_RESTORE_OPERATIONS_TOTAL,
            DB_RETENTION_CLEANUP_TOTAL,
            DB_TRANSACTION_TOTAL,
            DB_ROW_OPERATIONS_TOTAL,
            DB_BACKEND_INFO,
        )

        metrics = [
            DB_POOL_SIZE,
            DB_HEALTH_CHECK_TOTAL,
            DB_MIGRATION_RUNS_TOTAL,
            DB_BACKFILL_RECORDS_TOTAL,
            DB_BACKUP_OPERATIONS_TOTAL,
            DB_RESTORE_OPERATIONS_TOTAL,
            DB_RETENTION_CLEANUP_TOTAL,
            DB_TRANSACTION_TOTAL,
            DB_ROW_OPERATIONS_TOTAL,
            DB_BACKEND_INFO,
        ]

        for metric in metrics:
            assert metric._name.startswith("bess_db_"), f"{metric._name} should start with bess_db_"


class TestDbMetricsIntegration:
    """Integration tests for metrics recording."""

    def test_full_backup_restore_flow(self):
        """Test recording a full backup/restore flow."""
        from observability.db_metrics import (
            record_backup,
            record_restore,
            DB_BACKUP_OPERATIONS_TOTAL,
            DB_RESTORE_OPERATIONS_TOTAL,
        )

        # Record backup
        backup_initial = DB_BACKUP_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get()
        record_backup(format="custom", success=True, size_bytes=50*1024*1024, duration_seconds=30.0)
        assert DB_BACKUP_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get() == backup_initial + 1

        # Record restore
        restore_initial = DB_RESTORE_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get()
        record_restore(format="custom", success=True, duration_seconds=60.0)
        assert DB_RESTORE_OPERATIONS_TOTAL.labels(format="custom", result="success")._value.get() == restore_initial + 1

    def test_full_backfill_flow(self):
        """Test recording a full backfill flow."""
        from observability.db_metrics import (
            record_backfill,
            DB_BACKFILL_RECORDS_TOTAL,
        )

        # Record mixed results
        inserted_initial = DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="inserted")._value.get()
        skipped_initial = DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="skipped")._value.get()
        error_initial = DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="error")._value.get()

        record_backfill(table="run_index", result="inserted", count=100)
        record_backfill(table="run_index", result="skipped", count=20)
        record_backfill(table="run_index", result="error", count=2)

        assert DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="inserted")._value.get() == inserted_initial + 100
        assert DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="skipped")._value.get() == skipped_initial + 20
        assert DB_BACKFILL_RECORDS_TOTAL.labels(table="run_index", result="error")._value.get() == error_initial + 2

    def test_retention_cleanup_with_deletion(self):
        """Test retention cleanup records deletion count."""
        from observability.db_metrics import (
            record_retention_cleanup,
            DB_RETENTION_CLEANUP_TOTAL,
            DB_RETENTION_DELETED_TOTAL,
        )

        cleanup_initial = DB_RETENTION_CLEANUP_TOTAL.labels(store="audit", result="success")._value.get()
        deleted_initial = DB_RETENTION_DELETED_TOTAL.labels(store="audit")._value.get()

        record_retention_cleanup(store="audit", success=True, deleted_count=500)

        assert DB_RETENTION_CLEANUP_TOTAL.labels(store="audit", result="success")._value.get() == cleanup_initial + 1
        assert DB_RETENTION_DELETED_TOTAL.labels(store="audit")._value.get() == deleted_initial + 500
