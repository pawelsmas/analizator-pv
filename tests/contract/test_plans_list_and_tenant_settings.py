"""
Contract tests for plans and tenant settings API.

Tests verify:
- GET /plans returns list of available plans
- GET /tenant/settings returns tenant settings with plan info
- PATCH /tenant/settings updates plan and billing status
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plans_router import router as plans_router, get_quota_store
from quota_store import QuotaStore
from auth_config import AuthContext, Role
from auth_deps import require_role


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
    """Create FastAPI test app with plans router."""
    # Set auth mode to disabled for tests
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("DEFAULT_TENANT_ID", "test-tenant")

    # Need to reimport to pick up env changes
    import importlib
    import auth_config
    import auth_deps
    import plans_router as plans_router_module
    importlib.reload(auth_config)
    importlib.reload(auth_deps)

    # Reset the module-level singleton
    plans_router_module._quota_store = None

    app = FastAPI()

    # Override quota store dependency
    def override_get_quota_store():
        return test_store

    app.dependency_overrides[get_quota_store] = override_get_quota_store

    app.include_router(plans_router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


# -----------------------------------------------------------------------------
# GET /plans tests
# -----------------------------------------------------------------------------

class TestListPlans:
    """Tests for GET /plans endpoint."""

    def test_returns_200(self, client):
        """GET /plans should return 200."""
        response = client.get("/plans")
        assert response.status_code == 200

    def test_returns_items_array(self, client):
        """Response should contain items array."""
        response = client.get("/plans")
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_returns_total_count(self, client):
        """Response should contain total count."""
        response = client.get("/plans")
        data = response.json()
        assert "total" in data
        assert data["total"] == len(data["items"])

    def test_contains_default_plans(self, client):
        """Response should contain default plans (free, pro, enterprise)."""
        response = client.get("/plans")
        data = response.json()
        plan_ids = {p["id"] for p in data["items"]}

        assert "free" in plan_ids
        assert "pro" in plan_ids
        assert "enterprise" in plan_ids

    def test_plan_has_required_fields(self, client):
        """Each plan should have required fields."""
        response = client.get("/plans")
        data = response.json()

        for plan in data["items"]:
            assert "id" in plan
            assert "name" in plan
            assert "limits" in plan
            assert "is_default" in plan

    def test_plan_limits_structure(self, client):
        """Plan limits should have expected structure."""
        response = client.get("/plans")
        data = response.json()

        free_plan = next(p for p in data["items"] if p["id"] == "free")
        limits = free_plan["limits"]

        assert "jobs_per_day" in limits
        assert "reports_per_day" in limits
        assert "shares_total" in limits
        assert "storage_mb" in limits
        assert "projects_total" in limits

    def test_free_plan_is_marked_default(self, client):
        """Free plan should be marked as default."""
        response = client.get("/plans")
        data = response.json()

        free_plan = next(p for p in data["items"] if p["id"] == "free")
        assert free_plan["is_default"] is True

    def test_free_plan_has_correct_limits(self, client):
        """Free plan should have correct limit values."""
        response = client.get("/plans")
        data = response.json()

        free_plan = next(p for p in data["items"] if p["id"] == "free")
        limits = free_plan["limits"]

        assert limits["jobs_per_day"] == 10
        assert limits["reports_per_day"] == 5
        assert limits["shares_total"] == 10
        assert limits["storage_mb"] == 100
        assert limits["projects_total"] == 3

    def test_pro_plan_has_higher_limits(self, client):
        """Pro plan should have higher limits than free."""
        response = client.get("/plans")
        data = response.json()

        free_plan = next(p for p in data["items"] if p["id"] == "free")
        pro_plan = next(p for p in data["items"] if p["id"] == "pro")

        assert pro_plan["limits"]["jobs_per_day"] > free_plan["limits"]["jobs_per_day"]
        assert pro_plan["limits"]["storage_mb"] > free_plan["limits"]["storage_mb"]


# -----------------------------------------------------------------------------
# GET /tenant/settings tests
# -----------------------------------------------------------------------------

class TestGetTenantSettings:
    """Tests for GET /tenant/settings endpoint."""

    def test_returns_200(self, client):
        """GET /tenant/settings should return 200."""
        response = client.get("/tenant/settings")
        assert response.status_code == 200

    def test_response_has_tenant_id(self, client):
        """Should return correct tenant_id."""
        response = client.get("/tenant/settings")
        data = response.json()
        assert data["tenant_id"] == "test-tenant"

    def test_response_has_plan_id(self, client):
        """Should return a plan_id."""
        response = client.get("/tenant/settings")
        data = response.json()
        assert "plan_id" in data
        assert data["plan_id"] in ["free", "pro", "enterprise"]

    def test_response_has_billing_status(self, client):
        """Should return a billing_status."""
        response = client.get("/tenant/settings")
        data = response.json()
        assert "billing_status" in data
        assert data["billing_status"] in ["active", "suspended", "grace", "cancelled"]

    def test_returns_plan_name(self, client):
        """Response should include plan name."""
        response = client.get("/tenant/settings")
        data = response.json()
        assert "plan_name" in data
        assert data["plan_name"] in ["Free", "Pro", "Enterprise"]

    def test_returns_limits(self, client):
        """Response should include effective limits."""
        response = client.get("/tenant/settings")
        data = response.json()

        assert "limits" in data
        assert "jobs_per_day" in data["limits"]
        assert data["limits"]["jobs_per_day"] > 0

    def test_returns_timestamps(self, client):
        """Response should include timestamps."""
        response = client.get("/tenant/settings")
        data = response.json()

        assert "created_at" in data
        assert "updated_at" in data

    def test_grace_mode_until_is_present(self, client):
        """grace_mode_until should be in response."""
        response = client.get("/tenant/settings")
        data = response.json()
        # Can be None or a date string
        assert "grace_mode_until" in data


# -----------------------------------------------------------------------------
# PATCH /tenant/settings tests
# -----------------------------------------------------------------------------

class TestUpdateTenantSettings:
    """Tests for PATCH /tenant/settings endpoint."""

    def test_returns_200(self, client):
        """PATCH /tenant/settings should return 200."""
        # First create settings
        client.get("/tenant/settings")

        response = client.patch(
            "/tenant/settings",
            json={"billing_status": "active"},
        )
        assert response.status_code == 200

    def test_updates_plan_id(self, client):
        """Should update plan_id."""
        # First create settings
        client.get("/tenant/settings")

        response = client.patch(
            "/tenant/settings",
            json={"plan_id": "pro"},
        )
        data = response.json()

        assert data["plan_id"] == "pro"
        assert data["plan_name"] == "Pro"
        assert data["limits"]["jobs_per_day"] == 100

    def test_updates_billing_status(self, client):
        """Should update billing_status."""
        client.get("/tenant/settings")

        response = client.patch(
            "/tenant/settings",
            json={"billing_status": "suspended"},
        )
        data = response.json()

        assert data["billing_status"] == "suspended"

    def test_updates_grace_mode_until(self, client):
        """Should update grace_mode_until."""
        client.get("/tenant/settings")

        response = client.patch(
            "/tenant/settings",
            json={
                "billing_status": "grace",
                "grace_mode_until": "2026-02-01T00:00:00Z",
            },
        )
        data = response.json()

        assert data["billing_status"] == "grace"
        assert data["grace_mode_until"] == "2026-02-01T00:00:00Z"

    def test_rejects_invalid_plan_id(self, client):
        """Should reject invalid plan_id with 400."""
        client.get("/tenant/settings")

        response = client.patch(
            "/tenant/settings",
            json={"plan_id": "nonexistent"},
        )

        assert response.status_code == 400
        assert "Invalid plan_id" in response.json()["detail"]

    def test_rejects_invalid_billing_status(self, client):
        """Should reject invalid billing_status with 400."""
        client.get("/tenant/settings")

        response = client.patch(
            "/tenant/settings",
            json={"billing_status": "invalid"},
        )

        assert response.status_code == 400
        assert "Invalid billing_status" in response.json()["detail"]

    def test_valid_billing_statuses(self, client):
        """Should accept all valid billing statuses."""
        client.get("/tenant/settings")

        for status in ["active", "suspended", "grace", "cancelled"]:
            response = client.patch(
                "/tenant/settings",
                json={"billing_status": status},
            )
            assert response.status_code == 200
            assert response.json()["billing_status"] == status

    def test_partial_update(self, client):
        """Should allow partial updates."""
        client.get("/tenant/settings")

        # Update only plan
        client.patch("/tenant/settings", json={"plan_id": "pro"})

        # Update only status - plan should remain
        response = client.patch(
            "/tenant/settings",
            json={"billing_status": "suspended"},
        )
        data = response.json()

        assert data["plan_id"] == "pro"
        assert data["billing_status"] == "suspended"

    def test_empty_update_returns_current(self, client):
        """Empty update should return current settings."""
        # Get initial settings
        initial = client.get("/tenant/settings").json()

        # Empty patch should return same settings
        response = client.patch("/tenant/settings", json={})
        assert response.status_code == 200
        assert response.json()["plan_id"] == initial["plan_id"]
        assert response.json()["billing_status"] == initial["billing_status"]
