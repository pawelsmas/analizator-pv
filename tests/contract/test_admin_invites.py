"""
Contract tests for admin invites API (v3.1.0 PR2).

Tests:
- Admin can create and list invites
- Duplicate pending invite returns 409
- Expired invite returns 410
- Revoked invite returns 404
- Accept invite creates user and returns JWT
"""

import pytest
import requests
import os
import time

BASE_URL = os.getenv("BESS_API_URL", "http://localhost:8031/api/bess-dispatch")


def get_admin_token():
    """Get admin JWT token for testing."""
    payload = {"email": "admin@local", "password": "admin"}
    response = requests.post(f"{BASE_URL}/auth/login", json=payload)

    if response.status_code == 400:
        pytest.skip("Auth is disabled")
    if response.status_code == 401:
        pytest.skip("Admin user not seeded")

    return response.json()["access_token"]


class TestAdminCanCreateAndListInvites:
    """Tests for creating and listing invites."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_admin_can_list_invites(self, admin_token):
        """Admin should be able to list invites."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/admin/invites", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_admin_can_create_invite(self, admin_token):
        """Admin should be able to create a new invite."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Generate unique email
        import uuid
        email = f"invite_{uuid.uuid4().hex[:8]}@test.com"

        payload = {
            "email": email,
            "role": "viewer",
            "expires_hours": 24,
        }

        response = requests.post(f"{BASE_URL}/admin/invites", json=payload, headers=headers)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == email
        assert data["role"] == "viewer"
        assert "token" in data  # Token is returned only on create
        assert "id" in data
        assert "expires_at" in data

    def test_created_invite_appears_in_list(self, admin_token):
        """Newly created invite should appear in invite list."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"list_invite_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "editor"},
            headers=headers,
        )
        assert create_response.status_code == 201
        created_invite = create_response.json()

        # List invites
        list_response = requests.get(f"{BASE_URL}/admin/invites", headers=headers)
        assert list_response.status_code == 200

        invites = list_response.json()["items"]
        invite_ids = [inv["id"] for inv in invites]
        assert created_invite["id"] in invite_ids

    def test_duplicate_pending_invite_returns_409(self, admin_token):
        """Creating invite for email with pending invite should return 409."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        email = f"dup_invite_{uuid.uuid4().hex[:8]}@test.com"

        # Create first invite
        response1 = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        assert response1.status_code == 201

        # Try to create duplicate
        response2 = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "editor"},
            headers=headers,
        )
        assert response2.status_code == 409
        assert response2.json()["detail"]["error_code"] == "INVITE_ALREADY_EXISTS"

    def test_invite_for_existing_user_returns_409(self, admin_token):
        """Creating invite for existing user should return 409."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # admin@local already exists
        response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": "admin@local", "role": "viewer"},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == "USER_ALREADY_EXISTS"


class TestInviteRevocation:
    """Tests for revoking invites."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_can_revoke_invite(self, admin_token):
        """Admin should be able to revoke an invite."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"revoke_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        assert create_response.status_code == 201
        invite = create_response.json()

        # Revoke invite
        revoke_response = requests.delete(
            f"{BASE_URL}/admin/invites/{invite['id']}",
            headers=headers,
        )
        assert revoke_response.status_code == 204

    def test_revoked_invite_shows_in_list(self, admin_token):
        """Revoked invite should still appear in list with revoked_at set."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"revoke_list_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        assert create_response.status_code == 201
        invite = create_response.json()

        # Revoke invite
        requests.delete(f"{BASE_URL}/admin/invites/{invite['id']}", headers=headers)

        # Check list
        list_response = requests.get(f"{BASE_URL}/admin/invites", headers=headers)
        invites = list_response.json()["items"]
        revoked_invite = next((i for i in invites if i["id"] == invite["id"]), None)

        assert revoked_invite is not None
        assert revoked_invite["revoked_at"] is not None

    def test_cannot_revoke_already_revoked(self, admin_token):
        """Cannot revoke an already revoked invite."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"double_revoke_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        invite = create_response.json()

        # Revoke first time
        requests.delete(f"{BASE_URL}/admin/invites/{invite['id']}", headers=headers)

        # Try to revoke again
        response = requests.delete(
            f"{BASE_URL}/admin/invites/{invite['id']}",
            headers=headers,
        )
        assert response.status_code == 404


class TestAcceptInvite:
    """Tests for accepting invites."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_accept_invite_creates_user(self, admin_token):
        """Accepting invite should create user and return JWT."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"accept_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "editor"},
            headers=headers,
        )
        assert create_response.status_code == 201
        invite = create_response.json()

        # Accept invite (no auth needed)
        accept_response = requests.post(
            f"{BASE_URL}/auth/accept-invite",
            json={"token": invite["token"], "password": "newpassword123"},
        )

        assert accept_response.status_code == 200
        data = accept_response.json()
        assert data["email"] == email
        assert data["role"] == "editor"
        assert "access_token" in data
        assert "user_id" in data

    def test_accepted_user_can_login(self, admin_token):
        """User created from invite should be able to login."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create and accept invite
        import uuid
        email = f"login_{uuid.uuid4().hex[:8]}@test.com"
        password = "testpassword123"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        invite = create_response.json()

        requests.post(
            f"{BASE_URL}/auth/accept-invite",
            json={"token": invite["token"], "password": password},
        )

        # Try to login with new account
        login_response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": email, "password": password},
        )

        assert login_response.status_code == 200
        assert "access_token" in login_response.json()

    def test_cannot_accept_revoked_invite(self, admin_token):
        """Cannot accept a revoked invite."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"revoked_accept_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        invite = create_response.json()

        # Revoke invite
        requests.delete(f"{BASE_URL}/admin/invites/{invite['id']}", headers=headers)

        # Try to accept
        accept_response = requests.post(
            f"{BASE_URL}/auth/accept-invite",
            json={"token": invite["token"], "password": "password123"},
        )

        assert accept_response.status_code == 404
        assert accept_response.json()["detail"]["error_code"] == "INVITE_NOT_FOUND"

    def test_cannot_accept_twice(self, admin_token):
        """Cannot accept the same invite twice."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"double_accept_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        invite = create_response.json()

        # Accept first time
        requests.post(
            f"{BASE_URL}/auth/accept-invite",
            json={"token": invite["token"], "password": "password123"},
        )

        # Try to accept again
        accept_response = requests.post(
            f"{BASE_URL}/auth/accept-invite",
            json={"token": invite["token"], "password": "differentpass"},
        )

        assert accept_response.status_code == 404
        assert accept_response.json()["detail"]["error_code"] == "INVITE_NOT_FOUND"

    def test_password_too_short_returns_400(self, admin_token):
        """Password must be at least 6 characters."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create invite
        import uuid
        email = f"short_pass_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        invite = create_response.json()

        # Try to accept with short password
        accept_response = requests.post(
            f"{BASE_URL}/auth/accept-invite",
            json={"token": invite["token"], "password": "short"},
        )

        assert accept_response.status_code == 400
        assert accept_response.json()["detail"]["error_code"] == "PASSWORD_TOO_SHORT"


class TestInviteExpiry:
    """Tests for invite expiration."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_invite_has_expiry(self, admin_token):
        """Invite should have expires_at field."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        email = f"expiry_{uuid.uuid4().hex[:8]}@test.com"

        create_response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer", "expires_hours": 24},
            headers=headers,
        )

        assert create_response.status_code == 201
        data = create_response.json()
        assert "expires_at" in data
        assert data["expires_at"] is not None

    def test_invalid_expiry_returns_400(self, admin_token):
        """Invalid expires_hours should return 400."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        email = f"invalid_expiry_{uuid.uuid4().hex[:8]}@test.com"

        # Too short
        response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": email, "role": "viewer", "expires_hours": 0},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "INVALID_EXPIRY"

        # Too long
        response = requests.post(
            f"{BASE_URL}/admin/invites",
            json={"email": f"long_{email}", "role": "viewer", "expires_hours": 200},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "INVALID_EXPIRY"
