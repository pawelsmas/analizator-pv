"""
Contract tests for API key rotation (v3.2.0 PR5).

Verifies API key rotation, last_used_at tracking, and metrics.
Requires running API server with AUTH_MODE=enabled.
"""
import os
import pytest
import requests
from ._api import DEFAULT_BASE_URL


# Skip if auth is not enabled
AUTH_ENABLED = os.getenv("AUTH_MODE", "disabled").lower() == "enabled"


def get_admin_token():
    """Get admin JWT token for authenticated requests."""
    login_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
    resp = requests.post(
        login_url,
        json={"email": "admin@local", "password": "admin123"},
        timeout=10
    )
    if resp.status_code == 200:
        return resp.json().get("access_token")
    return None


@pytest.mark.skipif(
    not AUTH_ENABLED,
    reason="API key tests require AUTH_MODE=enabled"
)
class TestApiKeyRotation:
    """Test API key rotation functionality."""

    def test_rotate_api_key_returns_new_key(self):
        """POST /admin/api-keys/{key_id}/rotate should return new key."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}

        # First create a key
        create_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys"
        create_resp = requests.post(
            create_url,
            json={"label": "test-rotation", "role": "service"},
            headers=headers,
            timeout=10
        )

        if create_resp.status_code != 201:
            pytest.skip(f"Could not create API key: {create_resp.status_code}")

        old_key_data = create_resp.json()
        old_key_id = old_key_data["id"]
        old_api_key = old_key_data["api_key"]

        # Now rotate
        rotate_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys/{old_key_id}/rotate"
        rotate_resp = requests.post(rotate_url, headers=headers, timeout=10)

        assert rotate_resp.status_code == 200, (
            f"Expected 200, got {rotate_resp.status_code}: {rotate_resp.text}"
        )

        new_key_data = rotate_resp.json()
        assert "api_key" in new_key_data, "Response should have new api_key"
        assert new_key_data["api_key"] != old_api_key, "New key should be different"
        assert new_key_data["label"] == old_key_data["label"], "Label should be preserved"
        assert new_key_data["role"] == old_key_data["role"], "Role should be preserved"

    def test_rotated_key_has_rotated_from(self):
        """Rotated key should have rotated_from field set."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}

        # Create and rotate
        create_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys"
        create_resp = requests.post(
            create_url,
            json={"label": "test-rotated-from", "role": "service"},
            headers=headers,
            timeout=10
        )

        if create_resp.status_code != 201:
            pytest.skip("Could not create API key")

        old_key_id = create_resp.json()["id"]

        rotate_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys/{old_key_id}/rotate"
        rotate_resp = requests.post(rotate_url, headers=headers, timeout=10)

        if rotate_resp.status_code != 200:
            pytest.skip("Could not rotate key")

        # List keys and find the new one
        list_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys"
        list_resp = requests.get(list_url, headers=headers, timeout=10)

        assert list_resp.status_code == 200
        items = list_resp.json().get("items", [])

        # Find the new key (rotated_from should be old_key_id)
        new_key = next((k for k in items if k.get("rotated_from") == old_key_id), None)
        assert new_key is not None, f"Should find key with rotated_from={old_key_id}"

    def test_old_key_is_revoked_after_rotation(self):
        """Old key should be revoked after rotation."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}

        # Create key
        create_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys"
        create_resp = requests.post(
            create_url,
            json={"label": "test-revoke-on-rotate", "role": "service"},
            headers=headers,
            timeout=10
        )

        if create_resp.status_code != 201:
            pytest.skip("Could not create API key")

        old_key_id = create_resp.json()["id"]

        # Rotate
        rotate_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys/{old_key_id}/rotate"
        requests.post(rotate_url, headers=headers, timeout=10)

        # List keys and check old key is revoked
        list_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys"
        list_resp = requests.get(list_url, headers=headers, timeout=10)

        assert list_resp.status_code == 200
        items = list_resp.json().get("items", [])

        old_key = next((k for k in items if k["id"] == old_key_id), None)
        assert old_key is not None, "Old key should still be in list"
        assert old_key.get("revoked_at") is not None, "Old key should be revoked"

    def test_rotate_nonexistent_key_returns_404(self):
        """Rotating nonexistent key should return 404."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}

        rotate_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys/nonexistent-key-id/rotate"
        rotate_resp = requests.post(rotate_url, headers=headers, timeout=10)

        assert rotate_resp.status_code == 404


@pytest.mark.skipif(
    not AUTH_ENABLED,
    reason="API key tests require AUTH_MODE=enabled"
)
class TestApiKeyLastUsed:
    """Test last_used_at tracking."""

    def test_api_key_list_includes_last_used_at(self):
        """GET /admin/api-keys should include last_used_at field."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}
        list_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/admin/api-keys"
        list_resp = requests.get(list_url, headers=headers, timeout=10)

        assert list_resp.status_code == 200
        items = list_resp.json().get("items", [])

        # All keys should have last_used_at field (may be null)
        for item in items:
            assert "last_used_at" in item, "Each key should have last_used_at field"


class TestApiKeyMetrics:
    """Test API key metrics."""

    def test_metrics_endpoint_has_api_key_counters(self):
        """GET /metrics should include API key counters."""
        url = f"{DEFAULT_BASE_URL}/metrics"
        resp = requests.get(url, timeout=10)

        assert resp.status_code == 200
        content = resp.text

        # Check for API key metric definitions
        assert "bess_api_key" in content, (
            "API key metrics should be defined in /metrics"
        )
