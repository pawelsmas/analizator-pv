"""
Contract tests for auth disabled mode (v3.0.0 PR1).

When AUTH_MODE=disabled (default), all requests should be allowed without
authentication, and /auth/me should return auth_method='disabled'.
"""

import pytest
import requests

BASE_URL = "http://localhost:8031/api/bess-dispatch"


class TestAuthDisabledAllowsRequests:
    """Tests for disabled auth mode behavior."""

    def test_health_without_auth(self):
        """Health endpoint should work without auth."""
        response = requests.get("http://localhost:8031/health")
        assert response.status_code == 200

    def test_version_without_auth(self):
        """Version endpoint should work without auth."""
        response = requests.get("http://localhost:8031/version")
        assert response.status_code == 200

    def test_sizing_endpoint_without_auth(self):
        """Sizing endpoint should work without auth in disabled mode."""
        payload = {
            "load_profile_kwh": [100.0] * 8760,
            "pv_profile_kwh": [50.0] * 8760,
            "battery_variants": [
                {"name": "test", "energy_kwh": 100, "power_kw": 50, "capex_pln": 50000}
            ],
        }
        response = requests.post(f"{BASE_URL}/sizing", json=payload, timeout=30)
        # Should succeed or at least not return 401/403
        assert response.status_code not in [401, 403]

    def test_auth_me_returns_disabled_method(self):
        """/auth/me should return auth_method='disabled' when auth is off."""
        response = requests.get(f"{BASE_URL}/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["auth_method"] == "disabled"
        assert data["tenant_id"] == "default"

    def test_auth_me_returns_default_role(self):
        """/auth/me should return admin role when auth is disabled."""
        response = requests.get(f"{BASE_URL}/auth/me")
        assert response.status_code == 200
        data = response.json()
        # In disabled mode, user gets admin role
        assert data["role"] == "admin"

    def test_login_returns_error_when_disabled(self):
        """/auth/login should return 400 when auth is disabled."""
        payload = {"email": "test@test.com", "password": "test"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error_code"] == "AUTH_DISABLED"
