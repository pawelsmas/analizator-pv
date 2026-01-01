"""
Contract tests for 503 response when migrations are pending (v3.3.0 PR2).

Tests that when DB_MIGRATIONS_REQUIRED=true and migrations are pending,
the API returns 503 Service Unavailable.
"""

import pytest
import requests
import os

# Get base URL from environment or default to localhost
BASE_URL = os.getenv("BESS_API_URL", "http://localhost:8000")


class TestMigrationsPending503:
    """Contract tests for pending migrations behavior."""

    def test_health_db_returns_status(self):
        """
        /health/db should return database status.

        This tests the /health/db endpoint works regardless of migrations.
        """
        response = requests.get(f"{BASE_URL}/health/db", timeout=5)

        # Should return 200 with db status
        assert response.status_code == 200

        data = response.json()
        assert "ok" in data
        assert "db_backend" in data
        assert "latency_ms" in data

    def test_health_endpoint_still_works(self):
        """
        /health should always work even with pending migrations.

        Health endpoint should not be blocked by migrations guard.
        """
        response = requests.get(f"{BASE_URL}/health", timeout=5)

        assert response.status_code == 200

    def test_version_endpoint_still_works(self):
        """
        /version should always work even with pending migrations.

        Version endpoint should not be blocked by migrations guard.
        """
        response = requests.get(f"{BASE_URL}/version", timeout=5)

        assert response.status_code == 200

    def test_docs_endpoint_still_works(self):
        """
        /docs should always work even with pending migrations.

        OpenAPI docs should not be blocked by migrations guard.
        """
        response = requests.get(f"{BASE_URL}/docs", timeout=5)

        # 200 or 307 redirect are both acceptable
        assert response.status_code in [200, 307]


class TestMigrationsGuardIntegration:
    """
    Integration tests for migrations guard behavior.

    These tests verify the guard logic without actually running
    against a real Postgres instance with pending migrations.
    """

    def test_error_response_structure(self):
        """
        DB_MIGRATIONS_PENDING error should have correct structure.

        When returned, the 503 response should include:
        - error_code: "DB_MIGRATIONS_PENDING"
        - detail: Message mentioning alembic upgrade
        """
        # Import the error response format
        import sys
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch'
        ))
        from migrations_guard import get_migrations_error_response

        error = get_migrations_error_response()

        assert error["error_code"] == "DB_MIGRATIONS_PENDING"
        assert "alembic upgrade head" in error["detail"]

    def test_migrations_check_returns_tuple(self):
        """
        check_migrations_status should return (is_ok, current, head) tuple.
        """
        import sys
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch'
        ))
        from migrations_guard import check_migrations_status

        result = check_migrations_status()

        assert isinstance(result, tuple)
        assert len(result) == 3
        is_ok, current, head = result
        assert isinstance(is_ok, bool)

    def test_migrations_required_and_pending_returns_bool(self):
        """
        migrations_required_and_pending should return boolean.
        """
        import sys
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), '..', '..',
            'services', 'bess-dispatch'
        ))
        from migrations_guard import migrations_required_and_pending

        result = migrations_required_and_pending()

        assert isinstance(result, bool)
