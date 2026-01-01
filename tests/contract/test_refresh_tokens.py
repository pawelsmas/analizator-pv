"""
Contract tests for refresh tokens (v3.2.0 PR4).

Verifies refresh token flow: login, refresh, logout.
Requires running API server with AUTH_MODE=enabled.
"""
import os
import pytest
import requests
from ._api import DEFAULT_BASE_URL


# Skip if auth is not enabled
AUTH_ENABLED = os.getenv("AUTH_MODE", "disabled").lower() == "enabled"


@pytest.mark.skipif(
    not AUTH_ENABLED,
    reason="Refresh token tests require AUTH_MODE=enabled"
)
class TestRefreshTokenFlow:
    """Test refresh token flow."""

    def test_login_returns_refresh_token(self):
        """Login should return both access_token and refresh_token."""
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        # Use known test credentials
        login_payload = {"email": "admin@local", "password": "admin123"}

        resp = requests.post(url, json=login_payload, timeout=10)

        # If auth is enabled, should get 200 (or 401 if credentials wrong)
        if resp.status_code == 200:
            body = resp.json()
            assert "access_token" in body, "Response should have access_token"
            assert "refresh_token" in body, "Response should have refresh_token"
            assert "refresh_expires_in" in body, "Response should have refresh_expires_in"
            assert body["refresh_expires_in"] > 0, "refresh_expires_in should be positive"
        else:
            pytest.skip("Could not login with test credentials")

    def test_refresh_returns_new_access_token(self):
        """POST /auth/refresh should return new access_token."""
        login_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        refresh_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/refresh"

        # First login
        login_resp = requests.post(
            login_url,
            json={"email": "admin@local", "password": "admin123"},
            timeout=10
        )
        if login_resp.status_code != 200:
            pytest.skip("Could not login with test credentials")

        login_data = login_resp.json()
        refresh_token = login_data["refresh_token"]

        # Now refresh
        refresh_resp = requests.post(
            refresh_url,
            json={"refresh_token": refresh_token},
            timeout=10
        )

        assert refresh_resp.status_code == 200, (
            f"Expected 200, got {refresh_resp.status_code}: {refresh_resp.text}"
        )

        body = refresh_resp.json()
        assert "access_token" in body, "Response should have access_token"
        assert body["access_token"] != login_data["access_token"], (
            "New access_token should be different"
        )

    def test_refresh_with_rotation_returns_new_refresh_token(self):
        """With rotation enabled, refresh should return new refresh_token."""
        login_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        refresh_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/refresh"

        # Login
        login_resp = requests.post(
            login_url,
            json={"email": "admin@local", "password": "admin123"},
            timeout=10
        )
        if login_resp.status_code != 200:
            pytest.skip("Could not login with test credentials")

        login_data = login_resp.json()
        original_refresh = login_data["refresh_token"]

        # Refresh
        refresh_resp = requests.post(
            refresh_url,
            json={"refresh_token": original_refresh},
            timeout=10
        )

        if refresh_resp.status_code != 200:
            pytest.skip("Refresh failed")

        body = refresh_resp.json()
        # If rotation is enabled (default), should have new refresh_token
        if body.get("refresh_token"):
            assert body["refresh_token"] != original_refresh, (
                "New refresh_token should be different from original"
            )

    def test_used_refresh_token_is_rejected(self):
        """Once used, a refresh token should be rejected (rotation)."""
        login_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        refresh_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/refresh"

        # Login
        login_resp = requests.post(
            login_url,
            json={"email": "admin@local", "password": "admin123"},
            timeout=10
        )
        if login_resp.status_code != 200:
            pytest.skip("Could not login with test credentials")

        login_data = login_resp.json()
        original_refresh = login_data["refresh_token"]

        # First refresh (should work)
        first_refresh = requests.post(
            refresh_url,
            json={"refresh_token": original_refresh},
            timeout=10
        )
        if first_refresh.status_code != 200:
            pytest.skip("First refresh failed")

        # Second refresh with same token (should fail if rotation enabled)
        second_refresh = requests.post(
            refresh_url,
            json={"refresh_token": original_refresh},
            timeout=10
        )

        # With rotation, reusing token should fail
        assert second_refresh.status_code == 401, (
            f"Reused refresh token should return 401, got {second_refresh.status_code}"
        )

    def test_invalid_refresh_token_returns_401(self):
        """Invalid refresh token should return 401."""
        refresh_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/refresh"

        resp = requests.post(
            refresh_url,
            json={"refresh_token": "invalid_token_abc123"},
            timeout=10
        )

        assert resp.status_code == 401, (
            f"Expected 401 for invalid token, got {resp.status_code}"
        )
        body = resp.json()
        assert body.get("detail", {}).get("error_code") == "INVALID_REFRESH_TOKEN"


@pytest.mark.skipif(
    not AUTH_ENABLED,
    reason="Logout tests require AUTH_MODE=enabled"
)
class TestLogout:
    """Test logout endpoint."""

    def test_logout_revokes_refresh_token(self):
        """POST /auth/logout should revoke the refresh token."""
        login_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        logout_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/logout"
        refresh_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/refresh"

        # Login
        login_resp = requests.post(
            login_url,
            json={"email": "admin@local", "password": "admin123"},
            timeout=10
        )
        if login_resp.status_code != 200:
            pytest.skip("Could not login with test credentials")

        login_data = login_resp.json()
        access_token = login_data["access_token"]
        refresh_token = login_data["refresh_token"]

        # Logout
        logout_resp = requests.post(
            logout_url,
            json={"refresh_token": refresh_token},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )

        assert logout_resp.status_code == 200, (
            f"Logout should return 200, got {logout_resp.status_code}"
        )
        body = logout_resp.json()
        assert body.get("success") is True

        # Try to use the revoked token
        refresh_resp = requests.post(
            refresh_url,
            json={"refresh_token": refresh_token},
            timeout=10
        )

        assert refresh_resp.status_code == 401, (
            f"Revoked token should return 401, got {refresh_resp.status_code}"
        )


class TestRefreshTokenMetrics:
    """Test that refresh token metrics are exposed."""

    def test_metrics_endpoint_has_refresh_token_counters(self):
        """GET /metrics should include refresh token counters."""
        url = f"{DEFAULT_BASE_URL}/metrics"
        resp = requests.get(url, timeout=10)

        assert resp.status_code == 200

        content = resp.text

        # Check for refresh token metric definitions
        assert "bess_refresh_tokens" in content, (
            "Refresh token metrics should be defined in /metrics"
        )
