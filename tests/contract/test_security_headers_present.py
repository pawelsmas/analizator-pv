"""
Contract tests for security headers (v3.2.0).

Verifies that security headers are present in API responses.
Requires running API server at BASE_URL (default: localhost:8031).
"""
import pytest
import requests
from ._api import DEFAULT_BASE_URL


class TestSecurityHeadersPresent:
    """Test that security headers are present in responses."""

    def test_version_endpoint_has_security_headers(self):
        """GET /version should have all security headers."""
        url = f"{DEFAULT_BASE_URL}/version"
        response = requests.get(url, timeout=10)

        # Should succeed
        assert response.status_code == 200

        # Check required security headers
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Referrer-Policy") == "no-referrer"
        assert "geolocation=()" in response.headers.get("Permissions-Policy", "")
        assert "microphone=()" in response.headers.get("Permissions-Policy", "")
        assert "camera=()" in response.headers.get("Permissions-Policy", "")

    def test_health_endpoint_has_security_headers(self):
        """GET /health should have security headers."""
        url = f"{DEFAULT_BASE_URL}/health"
        response = requests.get(url, timeout=10)

        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_info_endpoint_has_security_headers(self):
        """GET /info should have security headers."""
        url = f"{DEFAULT_BASE_URL}/info"
        response = requests.get(url, timeout=10)

        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("Referrer-Policy") == "no-referrer"

    def test_no_hsts_in_dev_mode(self):
        """HSTS should not be present in dev mode."""
        url = f"{DEFAULT_BASE_URL}/version"
        response = requests.get(url, timeout=10)

        # In dev mode, HSTS should NOT be set
        # (test runs with ENV=dev by default)
        assert response.headers.get("Strict-Transport-Security") is None

    def test_permissions_policy_complete(self):
        """Permissions-Policy should restrict geolocation, microphone, camera."""
        url = f"{DEFAULT_BASE_URL}/version"
        response = requests.get(url, timeout=10)

        policy = response.headers.get("Permissions-Policy", "")
        assert "geolocation=()" in policy
        assert "microphone=()" in policy
        assert "camera=()" in policy
