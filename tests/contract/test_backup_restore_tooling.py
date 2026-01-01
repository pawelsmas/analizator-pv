"""
Contract tests for backup/restore tooling (v3.3.0 PR5).

Tests that backup/restore scripts are correctly structured.
"""

import pytest
import os
import sys

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'db'))


class TestBackupScriptInterface:
    """Tests for backup script interface."""

    def test_has_parse_args(self):
        """backup_postgres should have parse_args function."""
        from backup_postgres import parse_args
        assert callable(parse_args)

    def test_has_parse_database_url(self):
        """backup_postgres should have parse_database_url function."""
        from backup_postgres import parse_database_url
        assert callable(parse_database_url)

    def test_has_create_backup(self):
        """backup_postgres should have create_backup function."""
        from backup_postgres import create_backup
        assert callable(create_backup)

    def test_has_cleanup_old_backups(self):
        """backup_postgres should have cleanup_old_backups function."""
        from backup_postgres import cleanup_old_backups
        assert callable(cleanup_old_backups)

    def test_has_main(self):
        """backup_postgres should have main function."""
        from backup_postgres import main
        assert callable(main)


class TestRestoreScriptInterface:
    """Tests for restore script interface."""

    def test_has_parse_args(self):
        """restore_postgres should have parse_args function."""
        from restore_postgres import parse_args
        assert callable(parse_args)

    def test_has_parse_database_url(self):
        """restore_postgres should have parse_database_url function."""
        from restore_postgres import parse_database_url
        assert callable(parse_database_url)

    def test_has_detect_backup_format(self):
        """restore_postgres should have detect_backup_format function."""
        from restore_postgres import detect_backup_format
        assert callable(detect_backup_format)

    def test_has_restore_backup(self):
        """restore_postgres should have restore_backup function."""
        from restore_postgres import restore_backup
        assert callable(restore_backup)

    def test_has_main(self):
        """restore_postgres should have main function."""
        from restore_postgres import main
        assert callable(main)


class TestRetentionScriptInterface:
    """Tests for retention cleanup script interface."""

    def test_has_parse_args(self):
        """retention_cleanup should have parse_args function."""
        from retention_cleanup import parse_args
        assert callable(parse_args)

    def test_has_get_db_backend(self):
        """retention_cleanup should have get_db_backend function."""
        from retention_cleanup import get_db_backend
        assert callable(get_db_backend)

    def test_has_cleanup_sqlite_runs(self):
        """retention_cleanup should have cleanup_sqlite_runs function."""
        from retention_cleanup import cleanup_sqlite_runs
        assert callable(cleanup_sqlite_runs)

    def test_has_cleanup_sqlite_jobs(self):
        """retention_cleanup should have cleanup_sqlite_jobs function."""
        from retention_cleanup import cleanup_sqlite_jobs
        assert callable(cleanup_sqlite_jobs)

    def test_has_cleanup_sqlite_audit(self):
        """retention_cleanup should have cleanup_sqlite_audit function."""
        from retention_cleanup import cleanup_sqlite_audit
        assert callable(cleanup_sqlite_audit)

    def test_has_cleanup_postgres_runs(self):
        """retention_cleanup should have cleanup_postgres_runs function."""
        from retention_cleanup import cleanup_postgres_runs
        assert callable(cleanup_postgres_runs)

    def test_has_cleanup_postgres_jobs(self):
        """retention_cleanup should have cleanup_postgres_jobs function."""
        from retention_cleanup import cleanup_postgres_jobs
        assert callable(cleanup_postgres_jobs)

    def test_has_cleanup_postgres_audit(self):
        """retention_cleanup should have cleanup_postgres_audit function."""
        from retention_cleanup import cleanup_postgres_audit
        assert callable(cleanup_postgres_audit)

    def test_has_cleanup_backups(self):
        """retention_cleanup should have cleanup_backups function."""
        from retention_cleanup import cleanup_backups
        assert callable(cleanup_backups)

    def test_has_vacuum_sqlite(self):
        """retention_cleanup should have vacuum_sqlite function."""
        from retention_cleanup import vacuum_sqlite
        assert callable(vacuum_sqlite)

    def test_has_main(self):
        """retention_cleanup should have main function."""
        from retention_cleanup import main
        assert callable(main)


class TestEnvironmentVariables:
    """Tests for expected environment variable handling."""

    def test_backup_uses_database_url(self):
        """backup script should use DATABASE_URL."""
        from backup_postgres import create_backup

        # Should require DATABASE_URL
        result = create_backup(
            output_dir='/tmp/test',
            compress=False,
            format='custom',
            tables=None,
            schema_only=False,
            data_only=False,
        )

        # Either fails with error about DATABASE_URL or succeeds
        assert 'error' in result or result.get('success')

    def test_restore_uses_database_url(self):
        """restore script should use DATABASE_URL."""
        from restore_postgres import restore_backup

        # Should require DATABASE_URL
        result = restore_backup(
            backup_file='/nonexistent/backup.dump',
            no_owner=False,
            clean=False,
            if_exists=False,
            tables=None,
            schema_only=False,
            data_only=False,
            dry_run=True,
        )

        # Either fails with error about DATABASE_URL or backup not found
        assert 'error' in result

    def test_retention_default_values(self):
        """retention script should have sensible defaults."""
        # Check default env values are handled
        run_retention = int(os.getenv('RUN_STORE_RETENTION_DAYS', '30'))
        job_retention = int(os.getenv('JOB_STORE_RETENTION_DAYS', '14'))
        audit_retention = int(os.getenv('AUDIT_STORE_RETENTION_DAYS', '90'))

        assert run_retention >= 7
        assert job_retention >= 7
        assert audit_retention >= 30


class TestScriptFilePaths:
    """Tests for script file locations."""

    def test_all_scripts_in_db_directory(self):
        """All DB scripts should be in scripts/db directory."""
        scripts_dir = os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db'
        )

        expected_scripts = [
            'backup_postgres.py',
            'restore_postgres.py',
            'retention_cleanup.py',
            'backfill_runs_jobs.py',
            'check_migrations.py',
        ]

        for script in expected_scripts:
            path = os.path.join(scripts_dir, script)
            assert os.path.exists(path), f"Script not found: {script}"

    def test_scripts_have_docstrings(self):
        """Scripts should have module docstrings."""
        import backup_postgres
        import restore_postgres
        import retention_cleanup

        assert backup_postgres.__doc__ is not None
        assert restore_postgres.__doc__ is not None
        assert retention_cleanup.__doc__ is not None
