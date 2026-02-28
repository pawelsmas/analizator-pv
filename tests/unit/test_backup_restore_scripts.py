"""
Unit tests for backup/restore/retention scripts (v3.3.0 PR5).

Tests the CLI scripts for database backup, restore, and retention cleanup.
"""

import pytest
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'db'))


class TestBackupScript:
    """Tests for backup_postgres.py."""

    def test_backup_script_importable(self):
        """backup_postgres.py should be importable."""
        import backup_postgres
        assert backup_postgres is not None

    def test_parse_database_url(self):
        """parse_database_url should extract components correctly."""
        from backup_postgres import parse_database_url

        url = "postgresql://user:password@localhost:5432/mydb"
        result = parse_database_url(url)

        assert result['user'] == 'user'
        assert result['password'] == 'password'
        assert result['host'] == 'localhost'
        assert result['port'] == 5432
        assert result['database'] == 'mydb'

    def test_parse_database_url_default_port(self):
        """parse_database_url should use default port if not specified."""
        from backup_postgres import parse_database_url

        url = "postgresql://user:pass@host/db"
        result = parse_database_url(url)

        assert result['port'] == 5432

    def test_cleanup_old_backups_no_dir(self):
        """cleanup_old_backups should handle missing directory."""
        from backup_postgres import cleanup_old_backups

        result = cleanup_old_backups("/nonexistent/path", 7)

        assert result['deleted_count'] == 0
        assert result['freed_bytes'] == 0

    def test_cleanup_old_backups_empty_dir(self):
        """cleanup_old_backups should handle empty directory."""
        from backup_postgres import cleanup_old_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            result = cleanup_old_backups(tmpdir, 7)

            assert result['deleted_count'] == 0
            assert result['freed_bytes'] == 0


class TestRestoreScript:
    """Tests for restore_postgres.py."""

    def test_restore_script_importable(self):
        """restore_postgres.py should be importable."""
        import restore_postgres
        assert restore_postgres is not None

    def test_detect_backup_format_custom(self):
        """detect_backup_format should detect custom format."""
        from restore_postgres import detect_backup_format

        path = Path("/backup/bess_backup.dump")
        assert detect_backup_format(path) == 'custom'

    def test_detect_backup_format_plain(self):
        """detect_backup_format should detect plain SQL format."""
        from restore_postgres import detect_backup_format

        path = Path("/backup/bess_backup.sql")
        assert detect_backup_format(path) == 'plain'

    def test_detect_backup_format_compressed(self):
        """detect_backup_format should detect compressed SQL format."""
        from restore_postgres import detect_backup_format

        path = Path("/backup/bess_backup.sql.gz")
        assert detect_backup_format(path) == 'plain'

    def test_detect_backup_format_tar(self):
        """detect_backup_format should detect tar format."""
        from restore_postgres import detect_backup_format

        path = Path("/backup/bess_backup.tar")
        assert detect_backup_format(path) == 'tar'

    def test_parse_database_url_restore(self):
        """parse_database_url should work in restore script."""
        from restore_postgres import parse_database_url

        url = "postgresql://admin:secret@db.example.com:5433/bess_prod"
        result = parse_database_url(url)

        assert result['user'] == 'admin'
        assert result['password'] == 'secret'
        assert result['host'] == 'db.example.com'
        assert result['port'] == 5433
        assert result['database'] == 'bess_prod'


class TestRetentionScript:
    """Tests for retention_cleanup.py."""

    def test_retention_script_importable(self):
        """retention_cleanup.py should be importable."""
        import retention_cleanup
        assert retention_cleanup is not None

    def test_get_db_backend_default(self):
        """get_db_backend should return sqlite by default."""
        from retention_cleanup import get_db_backend

        # Save original value
        original = os.environ.get('DB_BACKEND')

        try:
            os.environ.pop('DB_BACKEND', None)
            result = get_db_backend()
            assert result == 'sqlite'
        finally:
            if original:
                os.environ['DB_BACKEND'] = original

    def test_get_db_backend_postgres(self):
        """get_db_backend should return postgres when configured."""
        from retention_cleanup import get_db_backend

        # Save original value
        original = os.environ.get('DB_BACKEND')

        try:
            os.environ['DB_BACKEND'] = 'postgres'
            result = get_db_backend()
            assert result == 'postgres'
        finally:
            if original:
                os.environ['DB_BACKEND'] = original
            else:
                os.environ.pop('DB_BACKEND', None)

    def test_cleanup_backups_no_dir(self):
        """cleanup_backups should handle missing directory."""
        from retention_cleanup import cleanup_backups

        # Save original
        original = os.environ.get('BACKUP_DIR')

        try:
            os.environ['BACKUP_DIR'] = '/nonexistent/backup/path'
            result = cleanup_backups(7, dry_run=True)
            assert result['deleted'] == 0
        finally:
            if original:
                os.environ['BACKUP_DIR'] = original
            else:
                os.environ.pop('BACKUP_DIR', None)

    def test_cleanup_sqlite_runs_missing_db(self):
        """cleanup_sqlite_runs should handle missing database."""
        from retention_cleanup import cleanup_sqlite_runs

        # Save original
        original = os.environ.get('RUN_STORE_PATH')

        try:
            os.environ['RUN_STORE_PATH'] = '/nonexistent/runs.sqlite'
            result = cleanup_sqlite_runs(30, dry_run=True)
            assert 'error' in result or result.get('deleted', 0) == 0
        finally:
            if original:
                os.environ['RUN_STORE_PATH'] = original
            else:
                os.environ.pop('RUN_STORE_PATH', None)


class TestScriptExistence:
    """Tests that scripts exist and are executable."""

    def test_backup_script_exists(self):
        """backup_postgres.py should exist."""
        path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db',
            'backup_postgres.py'
        )
        assert os.path.exists(path)

    def test_restore_script_exists(self):
        """restore_postgres.py should exist."""
        path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db',
            'restore_postgres.py'
        )
        assert os.path.exists(path)

    def test_retention_script_exists(self):
        """retention_cleanup.py should exist."""
        path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db',
            'retention_cleanup.py'
        )
        assert os.path.exists(path)

    def test_backfill_script_exists(self):
        """backfill_runs_jobs.py should exist."""
        path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db',
            'backfill_runs_jobs.py'
        )
        assert os.path.exists(path)

    def test_check_migrations_script_exists(self):
        """check_migrations.py should exist."""
        path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'scripts', 'db',
            'check_migrations.py'
        )
        assert os.path.exists(path)
