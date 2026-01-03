"""
Unit tests for Mapping API (v4.4.0 PR7).

Tests for /api/provisioning/mappings endpoints.
"""

import json
import pytest
import sys
import uuid
from unittest.mock import MagicMock, patch, PropertyMock


# Mock dependencies before importing
sys.modules['auth_decorators'] = MagicMock()
sys.modules['scim_store'] = MagicMock()
sys.modules['group_sync_engine'] = MagicMock()
sys.modules['auth_config'] = MagicMock()

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from flask import Flask, g


# Create a no-op require_admin decorator
def mock_require_admin(f):
    return f


# Patch the decorator before import
sys.modules['auth_decorators'].require_admin = mock_require_admin


@pytest.fixture
def app():
    """Create test Flask app."""
    app = Flask(__name__)
    app.config['TESTING'] = True

    # Import after mocking
    from mapping_api import mapping_api_bp
    app.register_blueprint(mapping_api_bp)

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return str(uuid.uuid4())


@pytest.fixture
def scim_group_id():
    """Test SCIM group ID."""
    return str(uuid.uuid4())


@pytest.fixture
def project_id():
    """Test project ID."""
    return str(uuid.uuid4())


@pytest.fixture
def mapping_id():
    """Test mapping ID."""
    return str(uuid.uuid4())


class TestListMappings:
    """Tests for GET /api/provisioning/mappings."""

    def test_list_mappings_returns_all_for_tenant(self, app, client, tenant_id, scim_group_id, project_id):
        """Test listing all mappings for tenant."""
        mock_store = MagicMock()
        mapping = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": True
        }
        mock_store.list_group_project_mappings.return_value = [mapping]
        mock_store.get_scim_group.return_value = {"display_name": "Test Group"}

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.get('/api/provisioning/mappings')

            assert response.status_code == 200
            data = response.get_json()
            assert data["total"] == 1
            assert data["mappings"][0]["group_display_name"] == "Test Group"

    def test_list_mappings_filters_by_scim_group_id(self, app, client, tenant_id, scim_group_id):
        """Test filtering by SCIM group ID."""
        mock_store = MagicMock()
        mock_store.list_group_project_mappings.return_value = []

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            client.get(f'/api/provisioning/mappings?scim_group_id={scim_group_id}')

            mock_store.list_group_project_mappings.assert_called_once_with(
                tenant_id=tenant_id,
                scim_group_id=scim_group_id,
                project_id=None
            )

    def test_list_mappings_filters_by_project_id(self, app, client, tenant_id, project_id):
        """Test filtering by project ID."""
        mock_store = MagicMock()
        mock_store.list_group_project_mappings.return_value = []

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            client.get(f'/api/provisioning/mappings?project_id={project_id}')

            mock_store.list_group_project_mappings.assert_called_once_with(
                tenant_id=tenant_id,
                scim_group_id=None,
                project_id=project_id
            )


class TestCreateMapping:
    """Tests for POST /api/provisioning/mappings."""

    def test_create_mapping_success(self, app, client, tenant_id, scim_group_id, project_id):
        """Test successful mapping creation."""
        mock_store = MagicMock()
        mock_engine = MagicMock()
        mapping_id = str(uuid.uuid4())

        mock_store.get_scim_group.return_value = {
            "id": scim_group_id,
            "tenant_id": tenant_id,
            "display_name": "Test Group"
        }
        mock_store.create_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": True
        }
        mock_engine.sync_group.return_value = {
            "members_added": 5,
            "errors": []
        }

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            with patch('mapping_api.get_sync_engine', return_value=mock_engine):
                @app.before_request
                def set_tenant():
                    g.tenant_id = tenant_id

                response = client.post(
                    '/api/provisioning/mappings',
                    json={
                        "scim_group_id": scim_group_id,
                        "project_id": project_id,
                        "role": "editor"
                    }
                )

                assert response.status_code == 201
                data = response.get_json()
                assert data["mapping"]["id"] == mapping_id
                assert data["sync_result"]["members_added"] == 5

    def test_create_mapping_missing_scim_group_id(self, app, client, tenant_id, project_id):
        """Test error when scim_group_id is missing."""
        @app.before_request
        def set_tenant():
            g.tenant_id = tenant_id

        response = client.post(
            '/api/provisioning/mappings',
            json={"project_id": project_id, "role": "editor"}
        )

        assert response.status_code == 400
        assert "scim_group_id is required" in response.get_json()["error"]

    def test_create_mapping_missing_project_id(self, app, client, tenant_id, scim_group_id):
        """Test error when project_id is missing."""
        @app.before_request
        def set_tenant():
            g.tenant_id = tenant_id

        response = client.post(
            '/api/provisioning/mappings',
            json={"scim_group_id": scim_group_id, "role": "editor"}
        )

        assert response.status_code == 400
        assert "project_id is required" in response.get_json()["error"]

    def test_create_mapping_missing_role(self, app, client, tenant_id, scim_group_id, project_id):
        """Test error when role is missing."""
        @app.before_request
        def set_tenant():
            g.tenant_id = tenant_id

        response = client.post(
            '/api/provisioning/mappings',
            json={"scim_group_id": scim_group_id, "project_id": project_id}
        )

        assert response.status_code == 400
        assert "role is required" in response.get_json()["error"]

    def test_create_mapping_invalid_role(self, app, client, tenant_id, scim_group_id, project_id):
        """Test error when role is invalid."""
        @app.before_request
        def set_tenant():
            g.tenant_id = tenant_id

        response = client.post(
            '/api/provisioning/mappings',
            json={"scim_group_id": scim_group_id, "project_id": project_id, "role": "superadmin"}
        )

        assert response.status_code == 400
        assert "role must be one of" in response.get_json()["error"]

    def test_create_mapping_group_not_found(self, app, client, tenant_id, scim_group_id, project_id):
        """Test error when SCIM group not found."""
        mock_store = MagicMock()
        mock_store.get_scim_group.return_value = None

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.post(
                '/api/provisioning/mappings',
                json={"scim_group_id": scim_group_id, "project_id": project_id, "role": "editor"}
            )

            assert response.status_code == 404
            assert "SCIM group not found" in response.get_json()["error"]

    def test_create_mapping_group_wrong_tenant(self, app, client, tenant_id, scim_group_id, project_id):
        """Test error when SCIM group belongs to different tenant."""
        mock_store = MagicMock()
        mock_store.get_scim_group.return_value = {
            "id": scim_group_id,
            "tenant_id": str(uuid.uuid4()),  # Different tenant
            "display_name": "Test Group"
        }

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.post(
                '/api/provisioning/mappings',
                json={"scim_group_id": scim_group_id, "project_id": project_id, "role": "editor"}
            )

            assert response.status_code == 404
            assert "SCIM group not found" in response.get_json()["error"]

    def test_create_mapping_duplicate(self, app, client, tenant_id, scim_group_id, project_id):
        """Test error when mapping already exists."""
        mock_store = MagicMock()
        mock_store.get_scim_group.return_value = {
            "id": scim_group_id,
            "tenant_id": tenant_id,
            "display_name": "Test Group"
        }
        mock_store.create_group_project_mapping.side_effect = Exception("UNIQUE constraint failed")

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.post(
                '/api/provisioning/mappings',
                json={"scim_group_id": scim_group_id, "project_id": project_id, "role": "editor"}
            )

            assert response.status_code == 409
            assert "Mapping already exists" in response.get_json()["error"]


class TestGetMapping:
    """Tests for GET /api/provisioning/mappings/<mapping_id>."""

    def test_get_mapping_success(self, app, client, tenant_id, mapping_id, scim_group_id, project_id):
        """Test successful mapping retrieval."""
        mock_store = MagicMock()
        mock_store.get_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": True
        }
        mock_store.get_scim_group.return_value = {"display_name": "Test Group"}

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.get(f'/api/provisioning/mappings/{mapping_id}')

            assert response.status_code == 200
            data = response.get_json()
            assert data["id"] == mapping_id
            assert data["group_display_name"] == "Test Group"

    def test_get_mapping_not_found(self, app, client, tenant_id, mapping_id):
        """Test error when mapping not found."""
        mock_store = MagicMock()
        mock_store.get_group_project_mapping.return_value = None

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.get(f'/api/provisioning/mappings/{mapping_id}')

            assert response.status_code == 404

    def test_get_mapping_wrong_tenant(self, app, client, tenant_id, mapping_id):
        """Test error when mapping belongs to different tenant."""
        mock_store = MagicMock()
        mock_store.get_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": str(uuid.uuid4()),  # Different tenant
            "role": "editor"
        }

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.get(f'/api/provisioning/mappings/{mapping_id}')

            assert response.status_code == 404


class TestUpdateMapping:
    """Tests for PATCH /api/provisioning/mappings/<mapping_id>."""

    def test_update_mapping_role(self, app, client, tenant_id, mapping_id, scim_group_id, project_id):
        """Test updating mapping role triggers re-sync."""
        mock_store = MagicMock()
        mock_engine = MagicMock()

        mock_store.get_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "viewer",
            "enabled": True
        }
        mock_store.update_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": True
        }
        mock_engine.sync_group.return_value = {"members_added": 0, "errors": []}

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            with patch('mapping_api.get_sync_engine', return_value=mock_engine):
                @app.before_request
                def set_tenant():
                    g.tenant_id = tenant_id

                response = client.patch(
                    f'/api/provisioning/mappings/{mapping_id}',
                    json={"role": "editor"}
                )

                assert response.status_code == 200
                # Should revoke old and sync new
                mock_engine.revoke_scim_memberships.assert_called_once()
                mock_engine.sync_group.assert_called_once()

    def test_update_mapping_disable(self, app, client, tenant_id, mapping_id, scim_group_id, project_id):
        """Test disabling mapping revokes memberships."""
        mock_store = MagicMock()
        mock_engine = MagicMock()

        mock_store.get_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": True
        }
        mock_store.update_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": False
        }
        mock_engine.revoke_scim_memberships.return_value = 5

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            with patch('mapping_api.get_sync_engine', return_value=mock_engine):
                @app.before_request
                def set_tenant():
                    g.tenant_id = tenant_id

                response = client.patch(
                    f'/api/provisioning/mappings/{mapping_id}',
                    json={"enabled": False}
                )

                assert response.status_code == 200
                data = response.get_json()
                assert data["sync_result"]["memberships_revoked"] == 5

    def test_update_mapping_enable(self, app, client, tenant_id, mapping_id, scim_group_id, project_id):
        """Test enabling mapping triggers sync."""
        mock_store = MagicMock()
        mock_engine = MagicMock()

        mock_store.get_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": False
        }
        mock_store.update_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": True
        }
        mock_engine.sync_group.return_value = {"members_added": 3, "errors": []}

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            with patch('mapping_api.get_sync_engine', return_value=mock_engine):
                @app.before_request
                def set_tenant():
                    g.tenant_id = tenant_id

                response = client.patch(
                    f'/api/provisioning/mappings/{mapping_id}',
                    json={"enabled": True}
                )

                assert response.status_code == 200
                mock_engine.sync_group.assert_called_once()

    def test_update_mapping_invalid_role(self, app, client, tenant_id, mapping_id):
        """Test error when updating with invalid role."""
        mock_store = MagicMock()
        mock_store.get_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "role": "editor",
            "enabled": True
        }

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.patch(
                f'/api/provisioning/mappings/{mapping_id}',
                json={"role": "superadmin"}
            )

            assert response.status_code == 400

    def test_update_mapping_not_found(self, app, client, tenant_id, mapping_id):
        """Test error when mapping not found."""
        mock_store = MagicMock()
        mock_store.get_group_project_mapping.return_value = None

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.patch(
                f'/api/provisioning/mappings/{mapping_id}',
                json={"role": "editor"}
            )

            assert response.status_code == 404


class TestDeleteMapping:
    """Tests for DELETE /api/provisioning/mappings/<mapping_id>."""

    def test_delete_mapping_success(self, app, client, tenant_id, mapping_id, scim_group_id, project_id):
        """Test successful mapping deletion."""
        mock_store = MagicMock()
        mock_engine = MagicMock()

        mock_store.get_group_project_mapping.return_value = {
            "id": mapping_id,
            "tenant_id": tenant_id,
            "scim_group_id": scim_group_id,
            "project_id": project_id,
            "role": "editor",
            "enabled": True
        }
        mock_engine.revoke_scim_memberships.return_value = 5

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            with patch('mapping_api.get_sync_engine', return_value=mock_engine):
                @app.before_request
                def set_tenant():
                    g.tenant_id = tenant_id

                response = client.delete(f'/api/provisioning/mappings/{mapping_id}')

                assert response.status_code == 200
                data = response.get_json()
                assert data["message"] == "Mapping deleted"
                assert data["memberships_revoked"] == 5
                mock_store.delete_group_project_mapping.assert_called_once_with(mapping_id)

    def test_delete_mapping_not_found(self, app, client, tenant_id, mapping_id):
        """Test error when mapping not found."""
        mock_store = MagicMock()
        mock_store.get_group_project_mapping.return_value = None

        with patch('mapping_api.get_scim_store', return_value=mock_store):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.delete(f'/api/provisioning/mappings/{mapping_id}')

            assert response.status_code == 404


class TestTriggerSync:
    """Tests for POST /api/provisioning/mappings/sync."""

    def test_sync_all_groups(self, app, client, tenant_id):
        """Test syncing all groups for tenant."""
        mock_engine = MagicMock()
        mock_engine.sync_all_groups.return_value = {
            "groups_processed": 3,
            "members_added": 10,
            "errors": []
        }

        with patch('mapping_api.get_sync_engine', return_value=mock_engine):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.post('/api/provisioning/mappings/sync', json={})

            assert response.status_code == 200
            mock_engine.sync_all_groups.assert_called_once_with(tenant_id)

    def test_sync_single_group(self, app, client, tenant_id, scim_group_id):
        """Test syncing a specific group."""
        mock_engine = MagicMock()
        mock_engine.sync_group.return_value = {
            "members_added": 5,
            "errors": []
        }

        with patch('mapping_api.get_sync_engine', return_value=mock_engine):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.post(
                '/api/provisioning/mappings/sync',
                json={"scim_group_id": scim_group_id}
            )

            assert response.status_code == 200
            mock_engine.sync_group.assert_called_once_with(scim_group_id)


class TestGetSyncStatus:
    """Tests for GET /api/provisioning/mappings/status."""

    def test_get_sync_status(self, app, client, tenant_id):
        """Test getting sync status."""
        mock_engine = MagicMock()
        mock_engine.get_sync_status.return_value = {
            "tenant_id": tenant_id,
            "scim_groups": 5,
            "enabled_mappings": 10,
            "scim_memberships": 50,
            "manual_memberships": 20
        }

        with patch('mapping_api.get_sync_engine', return_value=mock_engine):
            @app.before_request
            def set_tenant():
                g.tenant_id = tenant_id

            response = client.get('/api/provisioning/mappings/status')

            assert response.status_code == 200
            data = response.get_json()
            assert data["scim_groups"] == 5
            assert data["enabled_mappings"] == 10
