"""
Contract tests for auth enabled mode (v3.0.0 PR1).

When AUTH_MODE=enabled, requests to protected endpoints must include
a valid JWT token or API key.

Note: These tests require the backend to be running with AUTH_MODE=enabled.
If AUTH_MODE=disabled, these tests will be skipped.
"""

import pytest
import requests
import os

BASE_URL = "http://localhost:8031/api/bess-dispatch"


def is_auth_enabled():
    """Check if backend has auth enabled by calling /auth/me."""
    try:
        response = requests.get(f"{BASE_URL}/auth/me", timeout=5)
        if response.status_code == 200:
            return response.json().get("auth_method") != "disabled"
        return True  # If we can't reach, assume enabled
    except Exception:
        return False


@pytest.fixture(scope="module")
def auth_enabled():
    """Skip tests if auth is not enabled."""
    if not is_auth_enabled():
        pytest.skip("AUTH_MODE is disabled, skipping auth-enabled tests")
    return True


class TestAuthEnabledRequiresToken:
    """Tests for enabled auth mode behavior."""

    def test_sizing_without_auth_returns_401(self, auth_enabled):
        """Sizing endpoint should require auth when enabled."""
        payload = {
            "load_profile_kwh": [100.0] * 8760,
            "pv_profile_kwh": [50.0] * 8760,
            "battery_variants": [
                {"name": "test", "energy_kwh": 100, "power_kw": 50, "capex_pln": 50000}
            ],
        }
        response = requests.post(f"{BASE_URL}/sizing", json=payload, timeout=30)
        assert response.status_code == 401

    def test_auth_me_without_auth_returns_401(self, auth_enabled):
        """/auth/me should require auth when enabled."""
        response = requests.get(f"{BASE_URL}/auth/me")
        assert response.status_code == 401

    def test_invalid_token_returns_401(self, auth_enabled):
        """Invalid JWT token should return 401."""
        headers = {"Authorization": "Bearer invalid.token.here"}
        response = requests.get(f"{BASE_URL}/auth/me", headers=headers)
        assert response.status_code == 401

    def test_invalid_api_key_returns_401(self, auth_enabled):
        """Invalid API key should return 401."""
        headers = {"X-API-Key": "bess_invalid_key"}
        response = requests.get(f"{BASE_URL}/auth/me", headers=headers)
        assert response.status_code == 401

    def test_health_works_without_auth(self, auth_enabled):
        """Health endpoint should work even when auth is enabled."""
        response = requests.get("http://localhost:8031/health")
        assert response.status_code == 200

    def test_version_works_without_auth(self, auth_enabled):
        """Version endpoint should work even when auth is enabled."""
        response = requests.get("http://localhost:8031/version")
        assert response.status_code == 200


class TestAuthEnabledLogin:
    """Tests for login endpoint when auth is enabled."""

    def test_login_with_invalid_credentials_returns_401(self, auth_enabled):
        """Login with wrong credentials should return 401."""
        payload = {"email": "wrong@test.com", "password": "wrongpassword"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)
        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error_code"] == "INVALID_CREDENTIALS"

    def test_login_with_valid_credentials_returns_token(self, auth_enabled):
        """Login with valid credentials should return JWT token.

        Note: This test requires admin@local/admin user to exist.
        Set DEV_SEED_ADMIN=true when starting backend.
        """
        payload = {"email": "admin@local", "password": "admin"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)

        # This may fail if admin user wasn't seeded
        if response.status_code == 401:
            pytest.skip("Admin user not seeded (DEV_SEED_ADMIN=true required)")

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_token_can_access_protected_endpoint(self, auth_enabled):
        """JWT token from login should allow access to protected endpoints."""
        # Get token
        login_payload = {"email": "admin@local", "password": "admin"}
        login_response = requests.post(f"{BASE_URL}/auth/login", json=login_payload)

        if login_response.status_code == 401:
            pytest.skip("Admin user not seeded (DEV_SEED_ADMIN=true required)")

        token = login_response.json()["access_token"]

        # Use token to access /auth/me
        headers = {"Authorization": f"Bearer {token}"}
        me_response = requests.get(f"{BASE_URL}/auth/me", headers=headers)

        assert me_response.status_code == 200
        data = me_response.json()
        assert data["auth_method"] == "jwt"
        assert data["email"] == "admin@local"
        assert data["role"] == "admin"
