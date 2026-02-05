"""
Contract tests for usage API endpoints.

Tests verify:
- GET /usage returns tenant-level usage
- GET /usage/daily returns daily history
- GET /projects/{id}/usage returns project usage
- GET /usage/export/csv returns valid CSV
"""

import os
import sys
import tempfile
import pytest
import csv
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from usage_router import router as usage_router, get_quota_store
from quota_store import QuotaStore
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
    """Create FastAPI test app with usage router."""
    # Set auth mode to disabled for tests
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("DEFAULT_TENANT_ID", "test-tenant")

    # Need to reimport to pick up env changes
    import importlib
    import auth_config
    import auth_deps
    import usage_router as usage_router_module
    importlib.reload(auth_config)
    importlib.reload(auth_deps)

    # Reset the module-level singleton
    usage_router_module._quota_store = None

    # Configure quota engine to use test store
    monkeypatch.setattr(quota_engine, "_quota_store", test_store)

    app = FastAPI()

    # Override quota store dependency
    def override_get_quota_store():
        return test_store

    app.dependency_overrides[get_quota_store] = override_get_quota_store

    app.include_router(usage_router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


# -----------------------------------------------------------------------------
# GET /usage tests
# -----------------------------------------------------------------------------

class TestGetTenantUsage:
    """Tests for GET /usage endpoint."""

    def test_returns_200(self, client, test_store):
        """Should return 200."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage")

        assert response.status_code == 200

    def test_returns_tenant_id(self, client, test_store):
        """Should include tenant_id."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        assert data["tenant_id"] == "test-tenant"

    def test_returns_plan_id(self, client, test_store):
        """Should include plan_id."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        assert data["plan_id"] == "pro"

    def test_returns_quotas_list(self, client, test_store):
        """Should include quotas list."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        assert "quotas" in data
        assert isinstance(data["quotas"], list)
        assert len(data["quotas"]) > 0

    def test_quota_has_name(self, client, test_store):
        """Each quota should have name."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        for quota in data["quotas"]:
            assert "quota_name" in quota

    def test_quota_has_limit(self, client, test_store):
        """Each quota should have limit."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        jobs_quota = next(q for q in data["quotas"] if q["quota_name"] == "jobs_per_day")
        assert "limit" in jobs_quota
        assert jobs_quota["limit"] == 100  # Pro plan

    def test_quota_has_used(self, client, test_store):
        """Each quota should have used count."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        # Add some usage
        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 5})

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        jobs_quota = next(q for q in data["quotas"] if q["quota_name"] == "jobs_per_day")
        assert jobs_quota["used"] == 5

    def test_quota_has_remaining(self, client, test_store):
        """Each quota should have remaining count."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 30})

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        jobs_quota = next(q for q in data["quotas"] if q["quota_name"] == "jobs_per_day")
        assert jobs_quota["remaining"] == 70  # 100 - 30

    def test_quota_has_usage_pct(self, client, test_store):
        """Each quota should have usage percentage."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 50})

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        jobs_quota = next(q for q in data["quotas"] if q["quota_name"] == "jobs_per_day")
        assert jobs_quota["usage_pct"] == 50.0

    def test_aggregates_multiple_projects(self, client, test_store):
        """Should aggregate usage across multiple projects."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 10})
        test_store.upsert_usage_daily("test-tenant", "project-2", today, {"jobs_per_day": 20})

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        jobs_quota = next(q for q in data["quotas"] if q["quota_name"] == "jobs_per_day")
        assert jobs_quota["used"] == 30  # 10 + 20

    def test_includes_reset_at(self, client, test_store):
        """Should include reset_at timestamp."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage")
        data = response.json()

        assert "reset_at" in data
        assert data["reset_at"] is not None


# -----------------------------------------------------------------------------
# GET /usage/daily tests
# -----------------------------------------------------------------------------

class TestGetDailyUsage:
    """Tests for GET /usage/daily endpoint."""

    def test_returns_200(self, client, test_store):
        """Should return 200."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/daily")

        assert response.status_code == 200

    def test_returns_tenant_id(self, client, test_store):
        """Should include tenant_id."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/daily")
        data = response.json()

        assert data["tenant_id"] == "test-tenant"

    def test_returns_records_list(self, client, test_store):
        """Should include records list."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/daily")
        data = response.json()

        assert "records" in data
        assert isinstance(data["records"], list)

    def test_default_7_days(self, client, test_store):
        """Should return 7 days by default."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/daily")

        assert response.status_code == 200

    def test_accepts_days_param(self, client, test_store):
        """Should accept days parameter."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/daily?days=30")

        assert response.status_code == 200

    def test_accepts_project_id_filter(self, client, test_store):
        """Should accept project_id filter."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 5})
        test_store.upsert_usage_daily("test-tenant", "project-2", today, {"jobs_per_day": 10})

        response = client.get("/api/bess-dispatch/usage/daily?project_id=project-1")
        data = response.json()

        # Should only return project-1 records
        for record in data["records"]:
            assert record["project_id"] == "project-1"

    def test_record_has_date(self, client, test_store):
        """Records should have date."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 5})

        response = client.get("/api/bess-dispatch/usage/daily")
        data = response.json()

        assert len(data["records"]) > 0
        assert "date" in data["records"][0]

    def test_record_has_project_id(self, client, test_store):
        """Records should have project_id."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 5})

        response = client.get("/api/bess-dispatch/usage/daily")
        data = response.json()

        assert data["records"][0]["project_id"] == "project-1"

    def test_record_has_counters(self, client, test_store):
        """Records should have counters."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 5})

        response = client.get("/api/bess-dispatch/usage/daily")
        data = response.json()

        assert "counters" in data["records"][0]
        assert data["records"][0]["counters"]["jobs_per_day"] == 5


# -----------------------------------------------------------------------------
# GET /projects/{id}/usage tests
# -----------------------------------------------------------------------------

class TestGetProjectUsage:
    """Tests for GET /projects/{id}/usage endpoint."""

    def test_returns_200(self, client, test_store):
        """Should return 200."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage")

        assert response.status_code == 200

    def test_returns_project_id(self, client, test_store):
        """Should include project_id."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage")
        data = response.json()

        assert data["project_id"] == "project-1"

    def test_returns_tenant_id(self, client, test_store):
        """Should include tenant_id."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage")
        data = response.json()

        assert data["tenant_id"] == "test-tenant"

    def test_returns_quotas(self, client, test_store):
        """Should include quotas list."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage")
        data = response.json()

        assert "quotas" in data
        assert len(data["quotas"]) > 0

    def test_reflects_project_overrides(self, client, test_store):
        """Should reflect project-level overrides."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")
        test_store.upsert_project_quota("test-tenant", "project-1", {"jobs_per_day": 500})

        response = client.get("/api/bess-dispatch/projects/project-1/usage")
        data = response.json()

        jobs_quota = next(q for q in data["quotas"] if q["quota_name"] == "jobs_per_day")
        assert jobs_quota["limit"] == 500  # Override, not free plan's 10

    def test_has_overrides_flag_true(self, client, test_store):
        """Should set has_overrides=true when project has overrides."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="free")
        test_store.upsert_project_quota("test-tenant", "project-1", {"jobs_per_day": 500})

        response = client.get("/api/bess-dispatch/projects/project-1/usage")
        data = response.json()

        assert data["has_overrides"] is True

    def test_has_overrides_flag_false(self, client, test_store):
        """Should set has_overrides=false when project has no overrides."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage")
        data = response.json()

        assert data["has_overrides"] is False


# -----------------------------------------------------------------------------
# CSV Export tests
# -----------------------------------------------------------------------------

class TestExportUsageCsv:
    """Tests for GET /usage/export/csv endpoint."""

    def test_returns_200(self, client, test_store):
        """Should return 200."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/export/csv")

        assert response.status_code == 200

    def test_returns_csv_content_type(self, client, test_store):
        """Should return text/csv content type."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/export/csv")

        assert response.headers["content-type"] == "text/csv; charset=utf-8"

    def test_has_content_disposition_header(self, client, test_store):
        """Should have Content-Disposition header for download."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/export/csv")

        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]
        assert ".csv" in response.headers["content-disposition"]

    def test_csv_has_headers(self, client, test_store):
        """CSV should have column headers."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/export/csv")
        content = response.content.decode("utf-8")

        reader = csv.reader(io.StringIO(content))
        headers = next(reader)

        assert "date" in headers
        assert "project_id" in headers
        assert "jobs_per_day" in headers

    def test_csv_has_data_rows(self, client, test_store):
        """CSV should have data rows."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        today = test_store.get_today_date()
        test_store.upsert_usage_daily("test-tenant", "project-1", today, {"jobs_per_day": 5})

        response = client.get("/api/bess-dispatch/usage/export/csv")
        content = response.content.decode("utf-8")

        reader = csv.reader(io.StringIO(content))
        rows = list(reader)

        assert len(rows) >= 2  # Header + data

    def test_accepts_days_param(self, client, test_store):
        """Should accept days parameter."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/export/csv?days=60")

        assert response.status_code == 200

    def test_accepts_project_id_filter(self, client, test_store):
        """Should accept project_id filter."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/usage/export/csv?project_id=project-1")

        assert response.status_code == 200
        # Filename should include project ID
        assert "project-1" in response.headers["content-disposition"]


class TestExportProjectUsageCsv:
    """Tests for GET /projects/{id}/usage/export/csv endpoint."""

    def test_returns_200(self, client, test_store):
        """Should return 200."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage/export/csv")

        assert response.status_code == 200

    def test_returns_csv_content_type(self, client, test_store):
        """Should return text/csv content type."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage/export/csv")

        assert response.headers["content-type"] == "text/csv; charset=utf-8"

    def test_filename_includes_project_id(self, client, test_store):
        """Filename should include project ID."""
        test_store.upsert_tenant_settings("test-tenant", plan_id="pro")

        response = client.get("/api/bess-dispatch/projects/project-1/usage/export/csv")

        assert "project-1" in response.headers["content-disposition"]
