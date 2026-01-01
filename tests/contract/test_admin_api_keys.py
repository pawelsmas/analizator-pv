"""
Contract tests for admin API keys endpoints (v3.0.0 PR3).

Tests for:
- GET /admin/api-keys - list keys
- POST /admin/api-keys - create key
- DELETE /admin/api-keys/{key_id} - revoke key

Note: These tests require AUTH_MODE=enabled and admin credentials.
If AUTH_MODE=disabled, admin endpoints should return 403 for non-admin roles.
"""

import pytest
import requests

BASE_URL = "http://localhost:8031/api/bess-dispatch"


def get_auth_mode():
    """Determine current auth mode from /auth/me response."""
    try:
        response = requests.get(f"{BASE_URL}/auth/me", timeout=5)
        if response.status_code == 200:
            return response.json().get("auth_method", "unknown")
        return "enabled"
    except Exception:
        return "unknown"


def get_admin_token():
    """Get admin JWT token if auth is enabled."""
    payload = {"email": "admin@local", "password": "admin"}
    response = requests.post(f"{BASE_URL}/auth/login", json=payload)
    if response.status_code == 200:
        return response.json()["access_token"]
    return None


class TestAdminApiKeysEndpoints:
    """Tests for admin API keys endpoints."""

    def test_list_api_keys_without_auth_returns_401_or_403(self):
        """Listing API keys without auth should return 401 or 403."""
        response = requests.get(f"{BASE_URL}/admin/api-keys")
        # 401 if auth required, 403 if auth disabled but admin required
        assert response.status_code in [401, 403]

    def test_create_api_key_without_auth_returns_401_or_403(self):
        """Creating API key without auth should return 401 or 403."""
        payload = {"label": "Test Key", "role": "service"}
        response = requests.post(f"{BASE_URL}/admin/api-keys", json=payload)
        assert response.status_code in [401, 403]

    def test_revoke_api_key_without_auth_returns_401_or_403(self):
        """Revoking API key without auth should return 401 or 403."""
        response = requests.delete(f"{BASE_URL}/admin/api-keys/some-key-id")
        assert response.status_code in [401, 403]


class TestAdminApiKeysWithAuth:
    """Tests for admin API keys with authentication."""

    @pytest.fixture
    def admin_headers(self):
        """Get admin auth headers."""
        auth_mode = get_auth_mode()

        if auth_mode == "disabled":
            # In disabled mode, no auth needed but we're admin by default
            return {}

        token = get_admin_token()
        if token is None:
            pytest.skip("Admin user not seeded (DEV_SEED_ADMIN=true required)")
        return {"Authorization": f"Bearer {token}"}

    def test_list_api_keys_with_admin_auth(self, admin_headers):
        """Admin should be able to list API keys."""
        response = requests.get(f"{BASE_URL}/admin/api-keys", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_create_api_key_with_admin_auth(self, admin_headers):
        """Admin should be able to create API keys."""
        payload = {"label": "Test Service Key", "role": "service"}
        response = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "api_key" in data
        assert data["api_key"].startswith("bess_")
        assert data["label"] == "Test Service Key"
        assert data["role"] == "service"

    def test_create_api_key_returns_unique_keys(self, admin_headers):
        """Each created API key should be unique."""
        payload = {"label": "Unique Test Key", "role": "editor"}
        response1 = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )
        response2 = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )

        assert response1.status_code == 201
        assert response2.status_code == 201

        key1 = response1.json()["api_key"]
        key2 = response2.json()["api_key"]
        assert key1 != key2

    def test_create_admin_api_key_forbidden(self, admin_headers):
        """Creating admin API key should be forbidden."""
        payload = {"label": "Admin Key", "role": "admin"}
        response = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error_code"] == "ADMIN_KEY_FORBIDDEN"

    def test_create_api_key_invalid_role(self, admin_headers):
        """Creating API key with invalid role should fail."""
        payload = {"label": "Bad Key", "role": "superadmin"}
        response = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error_code"] == "INVALID_ROLE"

    def test_revoke_api_key_with_admin_auth(self, admin_headers):
        """Admin should be able to revoke API keys."""
        # First create a key
        payload = {"label": "Key to Revoke", "role": "viewer"}
        create_response = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )
        assert create_response.status_code == 201
        key_id = create_response.json()["id"]

        # Revoke the key
        revoke_response = requests.delete(
            f"{BASE_URL}/admin/api-keys/{key_id}",
            headers=admin_headers,
        )
        assert revoke_response.status_code == 204

    def test_revoke_nonexistent_key_returns_404(self, admin_headers):
        """Revoking non-existent key should return 404."""
        response = requests.delete(
            f"{BASE_URL}/admin/api-keys/nonexistent-key-id",
            headers=admin_headers,
        )
        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error_code"] == "KEY_NOT_FOUND"

    def test_created_key_appears_in_list(self, admin_headers):
        """Created API key should appear in list."""
        # Create a key
        unique_label = f"ListTest-{id(self)}"
        payload = {"label": unique_label, "role": "service"}
        create_response = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )
        assert create_response.status_code == 201
        key_id = create_response.json()["id"]

        # List keys
        list_response = requests.get(
            f"{BASE_URL}/admin/api-keys",
            headers=admin_headers,
        )
        assert list_response.status_code == 200

        # Find our key
        items = list_response.json()["items"]
        key_ids = [item["id"] for item in items]
        assert key_id in key_ids

    def test_revoked_key_still_in_list(self, admin_headers):
        """Revoked key should still appear in list with revoked_at."""
        # Create and revoke a key
        payload = {"label": "RevokedListTest", "role": "viewer"}
        create_response = requests.post(
            f"{BASE_URL}/admin/api-keys",
            json=payload,
            headers=admin_headers,
        )
        assert create_response.status_code == 201
        key_id = create_response.json()["id"]

        # Revoke it
        requests.delete(f"{BASE_URL}/admin/api-keys/{key_id}", headers=admin_headers)

        # List and check
        list_response = requests.get(
            f"{BASE_URL}/admin/api-keys",
            headers=admin_headers,
        )
        items = list_response.json()["items"]

        # Find our revoked key
        revoked_key = next((k for k in items if k["id"] == key_id), None)
        assert revoked_key is not None
        assert revoked_key["revoked_at"] is not None
