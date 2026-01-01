"""
Contract tests for admin users API (v3.1.0 PR1).

Tests:
- Admin can create and list users
- Last admin protection (409 on disable/demote)
- Email uniqueness (409)
"""

import pytest
import requests
import os

BASE_URL = os.getenv("BESS_API_URL", "http://localhost:8031/api/bess-dispatch")


def get_auth_mode():
    """Check if auth is enabled."""
    try:
        response = requests.get(f"{BASE_URL}/auth/me", timeout=5)
        if response.status_code == 200:
            return response.json().get("auth_method", "unknown")
        return "enabled"
    except Exception:
        return "unknown"


def get_admin_token():
    """Get admin JWT token for testing."""
    payload = {"email": "admin@local", "password": "admin"}
    response = requests.post(f"{BASE_URL}/auth/login", json=payload)

    if response.status_code == 400:
        pytest.skip("Auth is disabled")
    if response.status_code == 401:
        pytest.skip("Admin user not seeded")

    return response.json()["access_token"]


class TestAdminCanCreateAndListUsers:
    """Tests for creating and listing users."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_admin_can_list_users(self, admin_token):
        """Admin should be able to list users."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/admin/users", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_admin_can_create_user(self, admin_token):
        """Admin should be able to create a new user."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Generate unique email
        import uuid
        email = f"test_{uuid.uuid4().hex[:8]}@test.com"

        payload = {
            "email": email,
            "role": "viewer",
            "password": "testpassword123",
        }

        response = requests.post(f"{BASE_URL}/admin/users", json=payload, headers=headers)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == email
        assert data["role"] == "viewer"
        assert data["disabled"] is False
        assert "id" in data

    def test_created_user_appears_in_list(self, admin_token):
        """Newly created user should appear in user list."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create user
        import uuid
        email = f"list_test_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "editor", "password": "test123"},
            headers=headers,
        )
        assert create_response.status_code == 201
        created_user = create_response.json()

        # List users
        list_response = requests.get(f"{BASE_URL}/admin/users", headers=headers)
        assert list_response.status_code == 200

        users = list_response.json()["items"]
        user_ids = [u["id"] for u in users]
        assert created_user["id"] in user_ids

    def test_duplicate_email_returns_409(self, admin_token):
        """Creating user with duplicate email should return 409."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        email = f"dup_{uuid.uuid4().hex[:8]}@test.com"

        # Create first user
        response1 = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "viewer", "password": "test123"},
            headers=headers,
        )
        assert response1.status_code == 201

        # Try to create duplicate
        response2 = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "editor", "password": "test456"},
            headers=headers,
        )
        assert response2.status_code == 409
        assert response2.json()["detail"]["error_code"] == "EMAIL_ALREADY_EXISTS"


class TestLastAdminProtection:
    """Tests for last admin protection."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_cannot_disable_last_admin(self, admin_token):
        """Should return 409 when trying to disable the last admin."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Get the admin user (admin@local)
        list_response = requests.get(f"{BASE_URL}/admin/users", headers=headers)
        assert list_response.status_code == 200

        users = list_response.json()["items"]
        admin_users = [u for u in users if u["role"] == "admin" and not u["disabled"]]

        if len(admin_users) != 1:
            pytest.skip("Test requires exactly one active admin")

        admin_user = admin_users[0]

        # Try to disable the last admin
        response = requests.patch(
            f"{BASE_URL}/admin/users/{admin_user['id']}",
            json={"disabled": True},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == "LAST_ADMIN_PROTECTED"

    def test_cannot_demote_last_admin(self, admin_token):
        """Should return 409 when trying to demote the last admin."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Get the admin user
        list_response = requests.get(f"{BASE_URL}/admin/users", headers=headers)
        assert list_response.status_code == 200

        users = list_response.json()["items"]
        admin_users = [u for u in users if u["role"] == "admin" and not u["disabled"]]

        if len(admin_users) != 1:
            pytest.skip("Test requires exactly one active admin")

        admin_user = admin_users[0]

        # Try to demote the last admin to viewer
        response = requests.patch(
            f"{BASE_URL}/admin/users/{admin_user['id']}",
            json={"role": "viewer"},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == "LAST_ADMIN_PROTECTED"

    def test_can_demote_non_last_admin(self, admin_token):
        """Should be able to demote admin if there's another admin."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create a second admin
        import uuid
        email = f"admin2_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "admin", "password": "admin123"},
            headers=headers,
        )
        assert create_response.status_code == 201
        new_admin = create_response.json()

        # Now we can demote the new admin (original admin@local still exists)
        demote_response = requests.patch(
            f"{BASE_URL}/admin/users/{new_admin['id']}",
            json={"role": "viewer"},
            headers=headers,
        )

        assert demote_response.status_code == 200
        assert demote_response.json()["role"] == "viewer"


class TestUserUpdate:
    """Tests for user update functionality."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_can_update_user_role(self, admin_token):
        """Admin should be able to update user role."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create a user
        import uuid
        email = f"update_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "viewer", "password": "test123"},
            headers=headers,
        )
        assert create_response.status_code == 201
        user = create_response.json()

        # Update role
        update_response = requests.patch(
            f"{BASE_URL}/admin/users/{user['id']}",
            json={"role": "editor"},
            headers=headers,
        )

        assert update_response.status_code == 200
        assert update_response.json()["role"] == "editor"

    def test_can_disable_user(self, admin_token):
        """Admin should be able to disable a user."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create a user
        import uuid
        email = f"disable_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "viewer", "password": "test123"},
            headers=headers,
        )
        assert create_response.status_code == 201
        user = create_response.json()

        # Disable user
        update_response = requests.patch(
            f"{BASE_URL}/admin/users/{user['id']}",
            json={"disabled": True},
            headers=headers,
        )

        assert update_response.status_code == 200
        assert update_response.json()["disabled"] is True


class TestPasswordReset:
    """Tests for password reset functionality."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_admin_can_reset_password(self, admin_token):
        """Admin should be able to reset a user's password."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create a user
        import uuid
        email = f"reset_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "viewer", "password": "oldpassword"},
            headers=headers,
        )
        assert create_response.status_code == 201
        user = create_response.json()

        # Reset password
        reset_response = requests.post(
            f"{BASE_URL}/admin/users/{user['id']}/reset-password",
            json={"new_password": "newpassword123"},
            headers=headers,
        )

        assert reset_response.status_code == 204

    def test_password_too_short_returns_400(self, admin_token):
        """Password reset with too short password should return 400."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create a user
        import uuid
        email = f"short_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/users",
            json={"email": email, "role": "viewer", "password": "validpass"},
            headers=headers,
        )
        assert create_response.status_code == 201
        user = create_response.json()

        # Try to reset with short password
        reset_response = requests.post(
            f"{BASE_URL}/admin/users/{user['id']}/reset-password",
            json={"new_password": "short"},
            headers=headers,
        )

        assert reset_response.status_code == 400
        assert reset_response.json()["detail"]["error_code"] == "PASSWORD_TOO_SHORT"
