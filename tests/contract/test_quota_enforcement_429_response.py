"""
Contract tests for quota enforcement 429 responses.

Tests verify:
- 429 response when quota exceeded
- Retry-After header present
- Error response structure correct
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from quota_store import QuotaStore
from quota_enforcement import (
    QuotaExceededError,
    quota_exceeded_handler,
    check_and_enforce,
    QuotaEnforcer,
)
from auth_deps import get_auth_context, AuthContext
import quota_engine


# -----------------------------------------------------------------------------
# Test fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def test_store(temp_db):
    """Create a QuotaStore instance with temp database."""
    return QuotaStore(db_path=temp_db)


@pytest.fixture
def app(test_store, monkeypatch):
    """Create FastAPI test app with enforcement."""
    # Set auth mode to disabled for tests
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("DEFAULT_TENANT_ID", "test-tenant")
    monkeypatch.setenv("DEFAULT_PROJECT_ID", "test-project")

    # Need to reimport to pick up env changes
    import importlib
    import auth_config
    import auth_deps as auth_deps_module
    importlib.reload(auth_config)
    importlib.reload(auth_deps_module)

    # Configure quota engine to use test store
    monkeypatch.setattr(quota_engine, "_quota_store", test_store)

    app = FastAPI()

    # Add exception handler
    app.add_exception_handler(QuotaExceededError, quota_exceeded_handler)

    # Test endpoint that enforces quota
    @app.post("/test/jobs")
    async def create_test_job():
        # Use fixed tenant/project for testing
        check_and_enforce("test-tenant", "test-project", "jobs_per_day")
        return {"status": "created"}

    # Test endpoint with auth context (project_id comes from elsewhere, typically route param)
    @app.post("/test/jobs/with-auth")
    async def create_test_job_with_auth(auth: AuthContext = Depends(get_auth_context)):
        # In real usage, project_id would come from route param or request body
        # For this test, we use a fixed project_id
        check_and_enforce(auth.tenant_id, "test-project", "jobs_per_day")
        return {"status": "created"}

    # Test endpoint with QuotaEnforcer dependency
    @app.post("/test/reports")
    async def create_test_report():
        check_and_enforce("test-tenant", "test-project", "reports_per_day")
        return {"status": "created"}

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


# -----------------------------------------------------------------------------
# 429 Response tests
# -----------------------------------------------------------------------------

class TestQuotaExceeded429:
    """Tests for 429 QUOTA_EXCEEDED responses."""

    def test_returns_200_when_under_limit(self, client, test_store):
        """Should return 200 when under limit."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.post("/test/jobs")

        assert response.status_code == 200

    def test_returns_429_when_at_limit(self, client, test_store):
        """Should return 429 when quota exceeded."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        # Use up quota
        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")

        assert response.status_code == 429

    def test_has_retry_after_header(self, client, test_store):
        """Should include Retry-After header."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")

        assert "retry-after" in response.headers
        retry_after = int(response.headers["retry-after"])
        assert retry_after > 0
        assert retry_after <= 86400

    def test_response_has_code(self, client, test_store):
        """Should include error code in response."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")
        data = response.json()

        assert data["code"] == "QUOTA_EXCEEDED"

    def test_response_has_quota_name(self, client, test_store):
        """Should include quota name in response."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")
        data = response.json()

        assert data["quota_name"] == "jobs_per_day"

    def test_response_has_limit(self, client, test_store):
        """Should include limit in response."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")
        data = response.json()

        assert data["limit"] == 10

    def test_response_has_used(self, client, test_store):
        """Should include used count in response."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")
        data = response.json()

        assert data["used"] == 10

    def test_response_has_retry_after_seconds(self, client, test_store):
        """Should include retry_after_seconds in response."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")
        data = response.json()

        assert "retry_after_seconds" in data
        assert data["retry_after_seconds"] > 0

    def test_response_has_message(self, client, test_store):
        """Should include message in response."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")
        data = response.json()

        assert "message" in data
        assert "jobs_per_day" in data["message"]


# -----------------------------------------------------------------------------
# Different quota types tests
# -----------------------------------------------------------------------------

class TestDifferentQuotaTypes:
    """Tests for different quota types."""

    def test_reports_quota_returns_429(self, client, test_store):
        """Reports quota should return 429 when exceeded."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"reports_per_day": 5})

        response = client.post("/test/reports")

        assert response.status_code == 429
        assert response.json()["quota_name"] == "reports_per_day"


# -----------------------------------------------------------------------------
# Auth integration tests
# -----------------------------------------------------------------------------

class TestAuthIntegration:
    """Tests for auth context integration."""

    def test_works_with_auth_context(self, client, test_store):
        """Should work with auth context."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.post("/test/jobs/with-auth")

        assert response.status_code == 200

    def test_429_with_auth_context(self, client, test_store):
        """Should return 429 with auth context when exceeded."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs/with-auth")

        assert response.status_code == 429


# -----------------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases."""

    def test_allows_when_just_under_limit(self, client, test_store):
        """Should allow when just under limit."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 9})

        response = client.post("/test/jobs")

        assert response.status_code == 200

    def test_denies_at_exactly_limit(self, client, test_store):
        """Should deny when at exactly the limit."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 10})

        response = client.post("/test/jobs")

        assert response.status_code == 429

    def test_allows_with_project_override_unlimited(self, client, test_store):
        """Should allow when project has unlimited override."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")
        test_store.upsert_project_quota("test-tenant", "test-project", {"jobs_per_day": 0})

        # Even with high usage, should be allowed
        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 1000})

        response = client.post("/test/jobs")

        assert response.status_code == 200

    def test_allows_with_higher_project_override(self, client, test_store):
        """Should allow with higher project override."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")
        test_store.upsert_project_quota("test-tenant", "test-project", {"jobs_per_day": 100})

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "test-project", today, {"jobs_per_day": 50})

        response = client.post("/test/jobs")

        assert response.status_code == 200
