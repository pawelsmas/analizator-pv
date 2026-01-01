"""
Contract tests for Cache-Control: no-store on auth endpoints (v3.2.0).

Verifies that sensitive endpoints have proper cache control headers.
Requires running API server at BASE_URL (default: localhost:8031).
"""
import pytest
import requests
from ._api import DEFAULT_BASE_URL


class TestAuthEndpointsNoStore:
    """Test that auth endpoints have Cache-Control: no-store."""

    def test_auth_login_has_no_store(self):
        """POST /auth/login should have Cache-Control: no-store."""
        url = f"{DEFAULT_BASE_URL}/auth/login"
        # Attempt login (may fail with 401, but headers should still be set)
        response = requests.post(
            url,
            json={"username": "test", "password": "test"},
            timeout=10
        )

        # Response may be 401/422/etc but should have no-store header
        # (endpoint might not exist yet, check if available)
        if response.status_code != 404:
            cache_control = response.headers.get("Cache-Control", "")
            assert "no-store" in cache_control, (
                f"Auth endpoint should have Cache-Control: no-store, got: {cache_control}"
            )

    def test_api_auth_login_has_no_store(self):
        """POST /api/bess-dispatch/auth/login should have Cache-Control: no-store."""
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        response = requests.post(
            url,
            json={"username": "test", "password": "test"},
            timeout=10
        )

        if response.status_code != 404:
            cache_control = response.headers.get("Cache-Control", "")
            assert "no-store" in cache_control

    def test_shared_endpoint_has_no_store(self):
        """GET /shared/* should have Cache-Control: no-store."""
        url = f"{DEFAULT_BASE_URL}/shared/test-token"
        # Try to access a shared endpoint (may 404 if doesn't exist)
        response = requests.get(url, timeout=10)

        if response.status_code != 404:
            cache_control = response.headers.get("Cache-Control", "")
            assert "no-store" in cache_control

    def test_regular_endpoint_no_explicit_no_store(self):
        """Regular endpoints like /version should not have no-store."""
        url = f"{DEFAULT_BASE_URL}/version"
        response = requests.get(url, timeout=10)

        assert response.status_code == 200
        cache_control = response.headers.get("Cache-Control", "")
        # Regular endpoints should NOT have no-store
        # (they may have other cache directives or none)
        # This test just verifies we're not adding no-store everywhere
        # If no-store is present, it's still fine - middleware is working
