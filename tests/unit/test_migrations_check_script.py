"""
Unit tests for migrations check script (v3.3.0 PR2).

Tests the check_migrations.py script functionality.
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'db'))

from check_migrations import check_migrations, EXIT_OK, EXIT_PENDING, EXIT_ERROR


class TestCheckMigrationsScript:
    """Tests for check_migrations.py script."""

    def test_exit_codes_defined(self):
        """Exit codes should be properly defined."""
        assert EXIT_OK == 0
        assert EXIT_PENDING == 1
        assert EXIT_ERROR == 2

    @patch('check_migrations.get_sync_database_url')
    @patch('check_migrations.create_engine')
    @patch('check_migrations.Config')
    @patch('check_migrations.ScriptDirectory')
    def test_migrations_up_to_date(
        self,
        mock_script_dir,
        mock_config,
        mock_create_engine,
        mock_get_url,
    ):
        """Should return EXIT_OK when migrations are up to date."""
        # Setup mocks
        mock_get_url.return_value = "postgresql://test:test@localhost/test"

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # Mock MigrationContext
        with patch('check_migrations.MigrationContext') as mock_migration_ctx:
            mock_ctx = MagicMock()
            mock_ctx.get_current_revision.return_value = "abc123"
            mock_migration_ctx.configure.return_value = mock_ctx

            # Mock script directory
            mock_script = MagicMock()
            mock_script.get_current_head.return_value = "abc123"  # Same as current
            mock_script_dir.from_config.return_value = mock_script

            result = check_migrations()

            assert result == EXIT_OK

    @patch('check_migrations.get_sync_database_url')
    @patch('check_migrations.create_engine')
    @patch('check_migrations.Config')
    @patch('check_migrations.ScriptDirectory')
    def test_migrations_pending(
        self,
        mock_script_dir,
        mock_config,
        mock_create_engine,
        mock_get_url,
    ):
        """Should return EXIT_PENDING when migrations are pending."""
        # Setup mocks
        mock_get_url.return_value = "postgresql://test:test@localhost/test"

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # Mock MigrationContext
        with patch('check_migrations.MigrationContext') as mock_migration_ctx:
            mock_ctx = MagicMock()
            mock_ctx.get_current_revision.return_value = "abc123"
            mock_migration_ctx.configure.return_value = mock_ctx

            # Mock script directory
            mock_script = MagicMock()
            mock_script.get_current_head.return_value = "def456"  # Different from current
            mock_script_dir.from_config.return_value = mock_script

            result = check_migrations()

            assert result == EXIT_PENDING

    @patch('check_migrations.get_sync_database_url')
    def test_connection_error(self, mock_get_url):
        """Should return EXIT_ERROR on connection failure."""
        mock_get_url.side_effect = Exception("Connection refused")

        result = check_migrations()

        assert result == EXIT_ERROR

    @patch('check_migrations.get_sync_database_url')
    @patch('check_migrations.create_engine')
    def test_no_current_revision(
        self,
        mock_create_engine,
        mock_get_url,
    ):
        """Should return EXIT_PENDING when no current revision (fresh DB)."""
        mock_get_url.return_value = "postgresql://test:test@localhost/test"

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch('check_migrations.MigrationContext') as mock_migration_ctx:
            with patch('check_migrations.Config'):
                with patch('check_migrations.ScriptDirectory') as mock_script_dir:
                    mock_ctx = MagicMock()
                    mock_ctx.get_current_revision.return_value = None  # No migrations run
                    mock_migration_ctx.configure.return_value = mock_ctx

                    mock_script = MagicMock()
                    mock_script.get_current_head.return_value = "abc123"
                    mock_script_dir.from_config.return_value = mock_script

                    result = check_migrations()

                    assert result == EXIT_PENDING


class TestMigrationsGuard:
    """Tests for migrations_guard.py module."""

    def test_imports(self):
        """Module should import without errors."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch'
        ))
        from migrations_guard import (
            check_migrations_status,
            migrations_required_and_pending,
            get_migrations_error_response,
        )

        assert callable(check_migrations_status)
        assert callable(migrations_required_and_pending)
        assert callable(get_migrations_error_response)

    def test_error_response_format(self):
        """Error response should have correct format."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch'
        ))
        from migrations_guard import get_migrations_error_response

        response = get_migrations_error_response()

        assert "error_code" in response
        assert response["error_code"] == "DB_MIGRATIONS_PENDING"
        assert "detail" in response
        assert "alembic upgrade head" in response["detail"]

    @patch.dict(os.environ, {"DB_BACKEND": "sqlite"})
    def test_sqlite_mode_always_ok(self):
        """SQLite mode should always return OK (no migrations)."""
        # Re-import with patched env
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch'
        ))

        # Need to reload to pick up env change
        import importlib
        import db_config
        importlib.reload(db_config)

        from migrations_guard import check_migrations_status

        is_ok, current, head = check_migrations_status()

        # SQLite should always be OK
        assert is_ok is True
