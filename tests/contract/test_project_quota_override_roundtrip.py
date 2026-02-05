"""
Contract tests for project quota overrides API.

Tests verify:
- GET /projects/{id}/quotas returns project quotas
- PATCH /projects/{id}/quotas updates overrides
- Overrides are merged, not replaced
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_quotas_router import router as project_quotas_router, get_quota_store
from quota_store import QuotaStore


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
    """Create FastAPI test app with project quotas router."""
    # Set auth mode to disabled for tests
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("DEFAULT_TENANT_ID", "test-tenant")

    # Need to reimport to pick up env changes
    import importlib
    import auth_config
    import auth_deps
    import project_quotas_router as pqr_module
    importlib.reload(auth_config)
    importlib.reload(auth_deps)

    # Reset the module-level singleton
    pqr_module._quota_store = None

    app = FastAPI()

    # Override quota store dependency
    def override_get_quota_store():
        return test_store

    app.dependency_overrides[get_quota_store] = override_get_quota_store

    app.include_router(project_quotas_router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


# -----------------------------------------------------------------------------
# GET /projects/{id}/quotas tests
# -----------------------------------------------------------------------------

class TestGetProjectQuotas:
    """Tests for GET /projects/{id}/quotas endpoint."""

    def test_returns_200(self, client):
        """GET should return 200."""
        response = client.get("/projects/project-1/quotas")
        assert response.status_code == 200

    def test_returns_empty_overrides_for_new_project(self, client):
        """Should return empty overrides for project without quotas."""
        # Use a unique project name that's not used by other tests
        response = client.get("/projects/project-with-no-quotas-at-all/quotas")
        data = response.json()

        assert data["project_id"] == "project-with-no-quotas-at-all"
        assert data["overrides"] == {
            "jobs_per_day": None,
            "reports_per_day": None,
            "shares_total": None,
            "storage_mb": None,
        }

    def test_returns_existing_overrides(self, client):
        """Should return existing overrides if set."""
        # First create the override via API
        client.patch(
            "/projects/project-get-existing/quotas",
            json={"overrides": {"jobs_per_day": 200}},
        )

        response = client.get("/projects/project-get-existing/quotas")
        data = response.json()

        assert data["overrides"]["jobs_per_day"] == 200

    def test_response_has_timestamps_when_exists(self, client):
        """Should include timestamps when quota exists."""
        # First create the override via API
        client.patch(
            "/projects/project-with-timestamps/quotas",
            json={"overrides": {"jobs_per_day": 200}},
        )

        response = client.get("/projects/project-with-timestamps/quotas")
        data = response.json()

        assert "created_at" in data
        assert "updated_at" in data
        assert data["created_at"] is not None


# -----------------------------------------------------------------------------
# PATCH /projects/{id}/quotas tests
# -----------------------------------------------------------------------------

class TestUpdateProjectQuotas:
    """Tests for PATCH /projects/{id}/quotas endpoint."""

    def test_returns_200(self, client):
        """PATCH should return 200."""
        response = client.patch(
            "/projects/project-1/quotas",
            json={"overrides": {"jobs_per_day": 100}},
        )
        assert response.status_code == 200

    def test_creates_new_quota(self, client):
        """Should create quota for new project."""
        response = client.patch(
            "/projects/new-project/quotas",
            json={"overrides": {"jobs_per_day": 50}},
        )
        data = response.json()

        assert data["project_id"] == "new-project"
        assert data["overrides"]["jobs_per_day"] == 50

    def test_updates_existing_quota(self, client):
        """Should update existing quota."""
        # First create via API
        client.patch(
            "/projects/project-update-existing/quotas",
            json={"overrides": {"jobs_per_day": 100}},
        )

        # Then update
        response = client.patch(
            "/projects/project-update-existing/quotas",
            json={"overrides": {"jobs_per_day": 200}},
        )
        data = response.json()

        assert data["overrides"]["jobs_per_day"] == 200

    def test_merges_overrides(self, client):
        """Should merge new overrides with existing ones."""
        # Set initial override via API
        client.patch(
            "/projects/project-merge-test/quotas",
            json={"overrides": {"jobs_per_day": 100}},
        )

        # Add new override
        response = client.patch(
            "/projects/project-merge-test/quotas",
            json={"overrides": {"reports_per_day": 50}},
        )
        data = response.json()

        # Both should be present
        assert data["overrides"]["jobs_per_day"] == 100
        assert data["overrides"]["reports_per_day"] == 50

    def test_empty_overrides_returns_current(self, client):
        """Empty overrides should return current state."""
        # First set via API
        client.patch(
            "/projects/project-empty-override/quotas",
            json={"overrides": {"jobs_per_day": 100}},
        )

        response = client.patch(
            "/projects/project-empty-override/quotas",
            json={"overrides": {}},
        )
        data = response.json()

        assert data["overrides"]["jobs_per_day"] == 100

    def test_can_set_multiple_overrides(self, client):
        """Should accept multiple overrides at once."""
        response = client.patch(
            "/projects/project-1/quotas",
            json={
                "overrides": {
                    "jobs_per_day": 100,
                    "reports_per_day": 50,
                    "shares_total": 20,
                    "storage_mb": 500,
                }
            },
        )
        data = response.json()

        assert data["overrides"]["jobs_per_day"] == 100
        assert data["overrides"]["reports_per_day"] == 50
        assert data["overrides"]["shares_total"] == 20
        assert data["overrides"]["storage_mb"] == 500

    def test_returns_timestamps(self, client):
        """Should include timestamps in response."""
        response = client.patch(
            "/projects/project-1/quotas",
            json={"overrides": {"jobs_per_day": 100}},
        )
        data = response.json()

        assert "created_at" in data
        assert "updated_at" in data
        assert data["created_at"] is not None
        assert data["updated_at"] is not None


# -----------------------------------------------------------------------------
# Roundtrip tests
# -----------------------------------------------------------------------------

class TestQuotaRoundtrip:
    """Test complete roundtrip of quota operations."""

    def test_create_read_update(self, client):
        """Should support full CRUD workflow."""
        # Create
        create_response = client.patch(
            "/projects/test-project/quotas",
            json={"overrides": {"jobs_per_day": 100}},
        )
        assert create_response.status_code == 200
        assert create_response.json()["overrides"]["jobs_per_day"] == 100

        # Read
        read_response = client.get("/projects/test-project/quotas")
        assert read_response.status_code == 200
        assert read_response.json()["overrides"]["jobs_per_day"] == 100

        # Update
        update_response = client.patch(
            "/projects/test-project/quotas",
            json={"overrides": {"jobs_per_day": 200, "storage_mb": 1000}},
        )
        assert update_response.status_code == 200
        assert update_response.json()["overrides"]["jobs_per_day"] == 200
        assert update_response.json()["overrides"]["storage_mb"] == 1000

        # Read again
        final_response = client.get("/projects/test-project/quotas")
        assert final_response.json()["overrides"]["jobs_per_day"] == 200
        assert final_response.json()["overrides"]["storage_mb"] == 1000

    def test_different_projects_isolated(self, client):
        """Each project should have separate quotas."""
        # Set quotas for project-1
        client.patch(
            "/projects/project-1/quotas",
            json={"overrides": {"jobs_per_day": 100}},
        )

        # Set different quotas for project-2
        client.patch(
            "/projects/project-2/quotas",
            json={"overrides": {"jobs_per_day": 200}},
        )

        # Verify isolation
        p1 = client.get("/projects/project-1/quotas").json()
        p2 = client.get("/projects/project-2/quotas").json()

        assert p1["overrides"]["jobs_per_day"] == 100
        assert p2["overrides"]["jobs_per_day"] == 200

    def test_set_zero_is_valid(self, client):
        """Should accept zero as valid override."""
        response = client.patch(
            "/projects/project-1/quotas",
            json={"overrides": {"jobs_per_day": 0}},
        )
        assert response.status_code == 200
        assert response.json()["overrides"]["jobs_per_day"] == 0
