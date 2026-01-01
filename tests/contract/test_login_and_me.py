"""
Contract tests for /auth/login and /auth/me endpoints (v3.0.0 PR1).

Tests the auth API endpoints behavior in both disabled and enabled modes.
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
        return "enabled"  # If 401, auth is enabled
    except Exception:
        return "unknown"


class TestAuthMeEndpoint:
    """Tests for GET /auth/me endpoint."""

    def test_auth_me_returns_200_or_401(self):
        """/auth/me should return 200 (disabled) or 401 (enabled without token)."""
        response = requests.get(f"{BASE_URL}/auth/me")
        assert response.status_code in [200, 401]

    def test_auth_me_response_structure_when_accessible(self):
        """/auth/me response should have expected fields."""
        response = requests.get(f"{BASE_URL}/auth/me")

        if response.status_code != 200:
            pytest.skip("Auth is enabled, need token to access /auth/me")

        data = response.json()
        assert "tenant_id" in data
        assert "role" in data
        assert "auth_method" in data
        # user_id and email may be null in disabled mode
        assert "user_id" in data
        assert "email" in data

    def test_auth_me_role_is_valid(self):
        """/auth/me role should be a valid role value."""
        response = requests.get(f"{BASE_URL}/auth/me")

        if response.status_code != 200:
            pytest.skip("Auth is enabled, need token to access /auth/me")

        data = response.json()
        valid_roles = ["viewer", "editor", "admin", "service"]
        assert data["role"] in valid_roles


class TestAuthLoginEndpoint:
    """Tests for POST /auth/login endpoint."""

    def test_login_requires_email_and_password(self):
        """/auth/login should require email and password fields."""
        # Empty body
        response = requests.post(f"{BASE_URL}/auth/login", json={})
        assert response.status_code == 422  # Validation error

    def test_login_with_missing_email(self):
        """/auth/login should fail without email."""
        payload = {"password": "test"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)
        assert response.status_code == 422

    def test_login_with_missing_password(self):
        """/auth/login should fail without password."""
        payload = {"email": "test@test.com"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)
        assert response.status_code == 422

    def test_login_returns_400_or_401(self):
        """/auth/login should return 400 (disabled) or 401 (invalid creds)."""
        payload = {"email": "test@test.com", "password": "test"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)
        # 400 = auth disabled, 401 = invalid credentials
        assert response.status_code in [400, 401]


class TestAuthLoginResponseFormat:
    """Tests for login response format."""

    def test_login_error_has_detail_structure(self):
        """/auth/login error should have detail with error_code and message."""
        payload = {"email": "test@test.com", "password": "test"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)

        if response.status_code not in [400, 401]:
            pytest.skip("Unexpected response code")

        data = response.json()
        assert "detail" in data
        assert "error_code" in data["detail"]
        assert "message" in data["detail"]

    def test_login_disabled_error_code(self):
        """When auth disabled, login should return AUTH_DISABLED error."""
        auth_mode = get_auth_mode()

        if auth_mode != "disabled":
            pytest.skip("Auth is enabled, skipping disabled mode test")

        payload = {"email": "test@test.com", "password": "test"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error_code"] == "AUTH_DISABLED"


class TestAuthMeWithToken:
    """Tests for /auth/me with valid authentication."""

    @pytest.fixture
    def auth_token(self):
        """Get auth token if available."""
        payload = {"email": "admin@local", "password": "admin"}
        response = requests.post(f"{BASE_URL}/auth/login", json=payload)

        if response.status_code == 400:
            pytest.skip("Auth is disabled")
        if response.status_code == 401:
            pytest.skip("Admin user not seeded")

        return response.json()["access_token"]

    def test_auth_me_with_token_returns_jwt_method(self, auth_token):
        """/auth/me with JWT token should return auth_method='jwt'."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/auth/me", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["auth_method"] == "jwt"

    def test_auth_me_with_token_has_user_info(self, auth_token):
        """/auth/me with JWT token should include user info."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/auth/me", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] is not None
        assert data["email"] is not None
        assert data["tenant_id"] is not None
