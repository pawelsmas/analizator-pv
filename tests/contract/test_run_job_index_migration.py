"""
Contract tests for run_index and job_index migration (v3.3.0 PR4).

Tests that the migration creates the correct tables with proper schema.
"""

import pytest
import os
import sys

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestMigrationSchema:
    """Tests for migration schema correctness."""

    def test_migration_file_exists(self):
        """Migration file should exist."""
        migration_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch', 'alembic', 'versions',
            '2024_01_02_0002_add_run_job_index.py'
        )
        assert os.path.exists(migration_path)

    def test_migration_imports(self):
        """Migration should be importable."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch', 'alembic', 'versions'
        ))

        # Import without executing
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_0002",
            os.path.join(
                os.path.dirname(__file__), '..', '..',
                'services', 'bess-dispatch', 'alembic', 'versions',
                '2024_01_02_0002_add_run_job_index.py'
            )
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Check revision chain
        assert module.revision == '0002_run_job_index'
        assert module.down_revision == '0001_initial_baseline'

    def test_run_index_table_in_base(self):
        """run_index table should be in Base metadata."""
        from db_models import Base

        assert 'run_index' in Base.metadata.tables

    def test_job_index_table_in_base(self):
        """job_index table should be in Base metadata."""
        from db_models import Base

        assert 'job_index' in Base.metadata.tables


class TestRunIndexSchema:
    """Tests for run_index table schema."""

    def test_run_index_primary_key(self):
        """run_index should have run_id as primary key."""
        from db_models import RunIndex

        pk_columns = [c.name for c in RunIndex.__table__.primary_key.columns]
        assert pk_columns == ["run_id"]

    def test_run_index_tenant_column(self):
        """run_index should have tenant_id column with default."""
        from db_models import RunIndex

        tenant_col = RunIndex.__table__.columns['tenant_id']
        assert tenant_col.nullable is False
        assert tenant_col.default is not None or tenant_col.server_default is not None

    def test_run_index_created_at_column(self):
        """run_index should have created_at datetime column."""
        from db_models import RunIndex

        col = RunIndex.__table__.columns['created_at']
        assert col.nullable is False
        assert 'DateTime' in str(col.type)

    def test_run_index_blob_columns(self):
        """run_index should have blob columns."""
        from db_models import RunIndex

        columns = {c.name for c in RunIndex.__table__.columns}
        assert 'request_blob' in columns
        assert 'response_blob' in columns


class TestJobIndexSchema:
    """Tests for job_index table schema."""

    def test_job_index_primary_key(self):
        """job_index should have job_id as primary key."""
        from db_models import JobIndex

        pk_columns = [c.name for c in JobIndex.__table__.primary_key.columns]
        assert pk_columns == ["job_id"]

    def test_job_index_leasing_columns(self):
        """job_index should have leasing columns."""
        from db_models import JobIndex

        columns = {c.name for c in JobIndex.__table__.columns}

        assert 'lease_owner' in columns
        assert 'lease_expires_at' in columns
        assert 'attempts' in columns
        assert 'max_attempts' in columns
        assert 'started_at' in columns
        assert 'finished_at' in columns
        assert 'last_error' in columns

    def test_job_index_blob_columns(self):
        """job_index should have blob columns."""
        from db_models import JobIndex

        columns = {c.name for c in JobIndex.__table__.columns}
        assert 'request_blob' in columns
        assert 'result_blob' in columns


class TestBackfillScript:
    """Tests for backfill script."""

    def test_backfill_script_exists(self):
        """Backfill script should exist."""
        script_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'scripts', 'db', 'backfill_runs_jobs.py'
        )
        assert os.path.exists(script_path)

    def test_backfill_script_importable(self):
        """Backfill script should be importable."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db'
        ))

        # Should be able to import helper functions
        from backfill_runs_jobs import parse_datetime, count_sqlite_runs, count_sqlite_jobs

        assert callable(parse_datetime)
        assert callable(count_sqlite_runs)
        assert callable(count_sqlite_jobs)

    def test_parse_datetime_helper(self):
        """parse_datetime should handle various formats."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db'
        ))
        from backfill_runs_jobs import parse_datetime

        # ISO format
        result = parse_datetime("2024-01-15T12:00:00+00:00")
        assert result is not None
        assert result.year == 2024

        # With Z suffix
        result = parse_datetime("2024-01-15T12:00:00Z")
        assert result is not None

        # None input
        result = parse_datetime(None)
        assert result is None

        # Invalid format
        result = parse_datetime("invalid")
        assert result is None
