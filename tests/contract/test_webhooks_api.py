"""
Contract tests for webhooks API (v4.1.0).

Tests verify:
- CRUD operations for webhooks
- Secret rotation
- RBAC (admin vs project member)
- Event validation
"""

import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_config import AuthContext, Role
from webhook_store import WebhookStore


# -------------------------------------------------------------------------
# Test fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def webhook_store(temp_db):
    """Create a WebhookStore instance."""
    return WebhookStore(db_path=temp_db)


@pytest.fixture
def app(webhook_store):
    """Create test FastAPI app with webhooks router."""
    from webhooks_router import router, set_webhook_store

    app = FastAPI()
    app.include_router(router)
    set_webhook_store(webhook_store)

    return app


@pytest.fixture
def admin_auth():
    """Admin auth context."""
    return AuthContext(
        tenant_id="test-tenant",
        user_id="admin-user",
        email="admin@example.com",
        role=Role.ADMIN,
        auth_method="jwt",
    )


@pytest.fixture
def viewer_auth():
    """Viewer auth context."""
    return AuthContext(
        tenant_id="test-tenant",
        user_id="viewer-user",
        email="viewer@example.com",
        role=Role.VIEWER,
        auth_method="jwt",
    )


@pytest.fixture
def mock_auth_store():
    """Mock auth store for project access checks."""
    mock = MagicMock()
    mock.get_project.return_value = {
        "id": "project-1",
        "tenant_id": "test-tenant",
        "name": "Test Project",
    }
    mock.user_has_project_access.return_value = True
    return mock


@pytest.fixture
def client(app, admin_auth, mock_auth_store):
    """Test client with admin auth."""
    from webhooks_router import get_webhook_store
    from auth_deps import get_auth_context
    from auth_store import get_auth_store

    app.dependency_overrides[get_auth_context] = lambda: admin_auth

    with patch('webhooks_router.get_auth_store', return_value=mock_auth_store):
        yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def viewer_client(app, viewer_auth, mock_auth_store):
    """Test client with viewer auth."""
    from auth_deps import get_auth_context

    app.dependency_overrides[get_auth_context] = lambda: viewer_auth

    with patch('webhooks_router.get_auth_store', return_value=mock_auth_store):
        yield TestClient(app)

    app.dependency_overrides.clear()


# -------------------------------------------------------------------------
# Test: Create Webhook
# -------------------------------------------------------------------------

class TestCreateWebhook:
    """Tests for POST /webhooks."""

    def test_create_webhook_success(self, client):
        """Should create webhook and return secret."""
        response = client.post(
            "/webhooks",
            json={
                "name": "Test Webhook",
                "url": "https://example.com/hook",
                "events": ["job.succeeded", "job.failed"],
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "webhook" in data
        assert "secret" in data
        assert data["webhook"]["name"] == "Test Webhook"
        assert data["webhook"]["url"] == "https://example.com/hook"
        assert data["webhook"]["events"] == ["job.succeeded", "job.failed"]
        assert data["webhook"]["enabled"] is True
        assert data["webhook"]["secret_version"] == 1
        assert len(data["secret"]) > 20  # Reasonable secret length

    def test_create_webhook_with_project(self, client):
        """Should create project-scoped webhook."""
        response = client.post(
            "/webhooks?project_id=project-1",
            json={
                "name": "Project Webhook",
                "url": "https://example.com/hook",
                "events": ["report.generated"],
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["webhook"]["project_id"] == "project-1"

    def test_create_webhook_with_project_header(self, client):
        """Should accept project ID from header."""
        response = client.post(
            "/webhooks",
            headers={"X-Project-Id": "project-1"},
            json={
                "name": "Project Webhook",
                "url": "https://example.com/hook",
                "events": ["report.generated"],
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["webhook"]["project_id"] == "project-1"

    def test_create_webhook_invalid_event(self, client):
        """Should reject invalid event types."""
        response = client.post(
            "/webhooks",
            json={
                "name": "Test Webhook",
                "url": "https://example.com/hook",
                "events": ["invalid.event"],
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "INVALID_EVENTS"

    def test_create_webhook_empty_events(self, client):
        """Should reject empty events list."""
        response = client.post(
            "/webhooks",
            json={
                "name": "Test Webhook",
                "url": "https://example.com/hook",
                "events": [],
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "EVENTS_REQUIRED"

    def test_create_webhook_disabled(self, client):
        """Should create disabled webhook."""
        response = client.post(
            "/webhooks",
            json={
                "name": "Disabled Webhook",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
                "enabled": False,
            },
        )

        assert response.status_code == 201
        assert response.json()["webhook"]["enabled"] is False


# -------------------------------------------------------------------------
# Test: List Webhooks
# -------------------------------------------------------------------------

class TestListWebhooks:
    """Tests for GET /webhooks."""

    def test_list_webhooks_empty(self, client):
        """Should return empty list when no webhooks."""
        response = client.get("/webhooks")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_webhooks_returns_created(self, client):
        """Should return created webhooks."""
        # Create webhook
        client.post(
            "/webhooks",
            json={
                "name": "Test Webhook",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )

        response = client.get("/webhooks")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Test Webhook"

    def test_list_webhooks_filter_by_project(self, client):
        """Should filter by project ID."""
        # Create tenant-wide webhook
        client.post(
            "/webhooks",
            json={
                "name": "Tenant Webhook",
                "url": "https://example.com/hook1",
                "events": ["job.succeeded"],
            },
        )

        # Create project-scoped webhook
        client.post(
            "/webhooks?project_id=project-1",
            json={
                "name": "Project Webhook",
                "url": "https://example.com/hook2",
                "events": ["job.succeeded"],
            },
        )

        # List all
        response = client.get("/webhooks")
        assert response.json()["total"] == 2

        # List project only (include_tenant_wide=false to get only project-scoped)
        response = client.get("/webhooks?project_id=project-1&include_tenant_wide=false")
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["name"] == "Project Webhook"

        # List project with tenant-wide (default behavior)
        response = client.get("/webhooks?project_id=project-1")
        assert response.json()["total"] == 2

    def test_list_webhooks_requires_project_for_viewer(self, viewer_client):
        """Viewer should require project_id."""
        response = viewer_client.get("/webhooks")

        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "PROJECT_REQUIRED"


# -------------------------------------------------------------------------
# Test: Get Webhook
# -------------------------------------------------------------------------

class TestGetWebhook:
    """Tests for GET /webhooks/{webhook_id}."""

    def test_get_webhook_success(self, client):
        """Should return webhook details."""
        # Create webhook
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test Webhook",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        # Get webhook
        response = client.get(f"/webhooks/{webhook_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == webhook_id
        assert data["name"] == "Test Webhook"
        # Secret should NOT be included in get
        assert "secret" not in data

    def test_get_webhook_not_found(self, client):
        """Should return 404 for non-existent webhook."""
        response = client.get("/webhooks/non-existent-id")

        assert response.status_code == 404
        assert response.json()["detail"]["error_code"] == "WEBHOOK_NOT_FOUND"


# -------------------------------------------------------------------------
# Test: Update Webhook
# -------------------------------------------------------------------------

class TestUpdateWebhook:
    """Tests for PATCH /webhooks/{webhook_id}."""

    def test_update_webhook_name(self, client):
        """Should update webhook name."""
        # Create webhook
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Original Name",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        # Update name
        response = client.patch(
            f"/webhooks/{webhook_id}",
            json={"name": "Updated Name"},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_update_webhook_url(self, client):
        """Should update webhook URL."""
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test",
                "url": "https://example.com/old",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        response = client.patch(
            f"/webhooks/{webhook_id}",
            json={"url": "https://example.com/new"},
        )

        assert response.status_code == 200
        assert response.json()["url"] == "https://example.com/new"

    def test_update_webhook_events(self, client):
        """Should update webhook events."""
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        response = client.patch(
            f"/webhooks/{webhook_id}",
            json={"events": ["job.succeeded", "job.failed", "report.generated"]},
        )

        assert response.status_code == 200
        assert response.json()["events"] == ["job.succeeded", "job.failed", "report.generated"]

    def test_update_webhook_disable(self, client):
        """Should disable webhook."""
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        response = client.patch(
            f"/webhooks/{webhook_id}",
            json={"enabled": False},
        )

        assert response.status_code == 200
        assert response.json()["enabled"] is False

    def test_update_webhook_not_found(self, client):
        """Should return 404 for non-existent webhook."""
        response = client.patch(
            "/webhooks/non-existent-id",
            json={"name": "New Name"},
        )

        assert response.status_code == 404

    def test_update_webhook_invalid_events(self, client):
        """Should reject invalid events in update."""
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        response = client.patch(
            f"/webhooks/{webhook_id}",
            json={"events": ["invalid.event"]},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "INVALID_EVENTS"


# -------------------------------------------------------------------------
# Test: Delete Webhook
# -------------------------------------------------------------------------

class TestDeleteWebhook:
    """Tests for DELETE /webhooks/{webhook_id}."""

    def test_delete_webhook_success(self, client):
        """Should delete webhook."""
        # Create webhook
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        # Delete
        response = client.delete(f"/webhooks/{webhook_id}")
        assert response.status_code == 204

        # Verify deleted
        get_response = client.get(f"/webhooks/{webhook_id}")
        assert get_response.status_code == 404

    def test_delete_webhook_not_found(self, client):
        """Should return 404 for non-existent webhook."""
        response = client.delete("/webhooks/non-existent-id")
        assert response.status_code == 404


# -------------------------------------------------------------------------
# Test: Rotate Secret
# -------------------------------------------------------------------------

class TestRotateSecret:
    """Tests for POST /webhooks/{webhook_id}/rotate-secret."""

    def test_rotate_secret_success(self, client):
        """Should rotate secret and increment version."""
        # Create webhook
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]
        original_secret = create_response.json()["secret"]

        # Rotate
        response = client.post(f"/webhooks/{webhook_id}/rotate-secret")

        assert response.status_code == 200
        data = response.json()
        assert data["webhook_id"] == webhook_id
        assert data["secret"] != original_secret
        assert data["secret_version"] == 2

    def test_rotate_secret_multiple_times(self, client):
        """Should increment version on each rotation."""
        # Create webhook
        create_response = client.post(
            "/webhooks",
            json={
                "name": "Test",
                "url": "https://example.com/hook",
                "events": ["job.succeeded"],
            },
        )
        webhook_id = create_response.json()["webhook"]["id"]

        # Rotate multiple times
        for expected_version in [2, 3, 4]:
            response = client.post(f"/webhooks/{webhook_id}/rotate-secret")
            assert response.status_code == 200
            assert response.json()["secret_version"] == expected_version

    def test_rotate_secret_not_found(self, client):
        """Should return 404 for non-existent webhook."""
        response = client.post("/webhooks/non-existent-id/rotate-secret")
        assert response.status_code == 404


# -------------------------------------------------------------------------
# Test: Event Types Endpoint
# -------------------------------------------------------------------------

class TestEventTypes:
    """Tests for GET /webhooks/events/types."""

    def test_list_event_types(self, client):
        """Should list all supported event types."""
        response = client.get("/webhooks/events/types")

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert len(data["events"]) >= 5

        event_names = [e["name"] for e in data["events"]]
        assert "job.succeeded" in event_names
        assert "job.failed" in event_names
        assert "report.generated" in event_names
        assert "quota.exceeded" in event_names


# -------------------------------------------------------------------------
# Test: RBAC for Viewer
# -------------------------------------------------------------------------

class TestViewerRBAC:
    """Tests for viewer role access."""

    def test_viewer_cannot_create_tenant_webhook(self, app, viewer_auth, mock_auth_store):
        """Viewer should not create tenant-wide webhooks."""
        from auth_deps import get_auth_context

        app.dependency_overrides[get_auth_context] = lambda: viewer_auth

        with patch('webhooks_router.get_auth_store', return_value=mock_auth_store):
            client = TestClient(app)
            response = client.post(
                "/webhooks",
                json={
                    "name": "Test",
                    "url": "https://example.com/hook",
                    "events": ["job.succeeded"],
                },
            )

        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "ADMIN_REQUIRED"
        app.dependency_overrides.clear()

    def test_viewer_can_list_project_webhooks(self, app, viewer_auth, mock_auth_store, webhook_store):
        """Viewer should list project webhooks they have access to."""
        from auth_deps import get_auth_context
        from webhooks_router import set_webhook_store

        set_webhook_store(webhook_store)

        # Create a project webhook as admin first
        webhook_store.create_webhook(
            tenant_id="test-tenant",
            name="Project Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
            project_id="project-1",
        )

        app.dependency_overrides[get_auth_context] = lambda: viewer_auth

        with patch('webhooks_router.get_auth_store', return_value=mock_auth_store):
            client = TestClient(app)
            response = client.get("/webhooks?project_id=project-1")

        assert response.status_code == 200
        assert response.json()["total"] == 1
        app.dependency_overrides.clear()
