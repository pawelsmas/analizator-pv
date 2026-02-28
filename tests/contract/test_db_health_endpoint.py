"""
Contract tests for database health endpoint (v3.3.0 PR1).

Verifies /health/db endpoint returns connectivity status.
Requires running API server at BASE_URL (default: localhost:8031).
"""
import requests
from ._api import DEFAULT_BASE_URL


class TestDBHealthEndpoint:
    """Test database health endpoint."""

    def test_health_db_endpoint_exists(self):
        """GET /health/db should return 200 with db status."""
        url = f"{DEFAULT_BASE_URL}/health/db"
        resp = requests.get(url, timeout=10)

        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

    def test_health_db_returns_expected_fields(self):
        """Response should have ok, db_backend, latency_ms fields."""
        url = f"{DEFAULT_BASE_URL}/health/db"
        resp = requests.get(url, timeout=10)

        if resp.status_code != 200:
            return  # Skip field check if endpoint not available

        body = resp.json()
        assert "ok" in body, "Response should have 'ok' field"
        assert "db_backend" in body, "Response should have 'db_backend' field"
        assert "latency_ms" in body, "Response should have 'latency_ms' field"

    def test_health_db_ok_is_boolean(self):
        """The 'ok' field should be a boolean."""
        url = f"{DEFAULT_BASE_URL}/health/db"
        resp = requests.get(url, timeout=10)

        if resp.status_code != 200:
            return

        body = resp.json()
        assert isinstance(body.get("ok"), bool), "ok should be boolean"

    def test_health_db_backend_is_string(self):
        """The 'db_backend' field should be a string (sqlite or postgres)."""
        url = f"{DEFAULT_BASE_URL}/health/db"
        resp = requests.get(url, timeout=10)

        if resp.status_code != 200:
            return

        body = resp.json()
        db_backend = body.get("db_backend")
        assert isinstance(db_backend, str), "db_backend should be string"
        assert db_backend in ("sqlite", "postgres"), (
            f"db_backend should be 'sqlite' or 'postgres', got: {db_backend}"
        )

    def test_health_db_latency_is_positive(self):
        """The 'latency_ms' field should be a non-negative integer."""
        url = f"{DEFAULT_BASE_URL}/health/db"
        resp = requests.get(url, timeout=10)

        if resp.status_code != 200:
            return

        body = resp.json()
        latency_ms = body.get("latency_ms")
        assert isinstance(latency_ms, int), "latency_ms should be integer"
        assert latency_ms >= 0, "latency_ms should be non-negative"

    def test_health_db_sqlite_mode_returns_ok(self):
        """In sqlite mode (default), should return ok=true."""
        url = f"{DEFAULT_BASE_URL}/health/db"
        resp = requests.get(url, timeout=10)

        if resp.status_code != 200:
            return

        body = resp.json()
        # In default sqlite mode, should always be ok
        if body.get("db_backend") == "sqlite":
            assert body.get("ok") is True, (
                f"SQLite mode should be ok, got: {body}"
            )
