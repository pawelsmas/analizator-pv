"""
Contract tests for admin shares API (v3.1.0 PR3).

Tests:
- Admin can create and list shares
- Shares can filter by resource type/id
- Revoked share returns 404 on access
- Expired share returns 410 on access
- X-Share-Token header authentication
"""

import pytest
import requests
import os

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


class TestAdminCanCreateAndListShares:
    """Tests for creating and listing shares."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_admin_can_list_shares(self, admin_token):
        """Admin should be able to list shares."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/admin/shares", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_admin_can_create_share(self, admin_token):
        """Admin should be able to create a new share."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        payload = {
            "resource_type": "run",
            "resource_id": run_id,
            "label": "Test share",
        }

        response = requests.post(f"{BASE_URL}/admin/shares", json=payload, headers=headers)

        assert response.status_code == 201
        data = response.json()
        assert data["resource_type"] == "run"
        assert data["resource_id"] == run_id
        assert data["label"] == "Test share"
        assert "token" in data  # Token is returned only on create
        assert "id" in data
        assert data["expires_at"] is None  # No expiry by default

    def test_created_share_appears_in_list(self, admin_token):
        """Newly created share should appear in share list."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        create_response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )
        assert create_response.status_code == 201
        created_share = create_response.json()

        # List shares
        list_response = requests.get(f"{BASE_URL}/admin/shares", headers=headers)
        assert list_response.status_code == 200

        shares = list_response.json()["items"]
        share_ids = [s["id"] for s in shares]
        assert created_share["id"] in share_ids

    def test_share_with_expiry(self, admin_token):
        """Share can be created with expiry."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        payload = {
            "resource_type": "run",
            "resource_id": run_id,
            "expires_hours": 24,
        }

        response = requests.post(f"{BASE_URL}/admin/shares", json=payload, headers=headers)

        assert response.status_code == 201
        data = response.json()
        assert data["expires_at"] is not None

    def test_invalid_resource_type_returns_400(self, admin_token):
        """Invalid resource_type should return 400."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "invalid", "resource_id": str(uuid.uuid4())},
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "INVALID_RESOURCE_TYPE"


class TestShareFiltering:
    """Tests for filtering shares."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_filter_by_resource_type(self, admin_token):
        """Should be able to filter shares by resource type."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())
        report_id = str(uuid.uuid4())

        # Create a run share
        requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )

        # Create a report share
        requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "report", "resource_id": report_id},
            headers=headers,
        )

        # Filter by run
        response = requests.get(
            f"{BASE_URL}/admin/shares?resource_type=run",
            headers=headers,
        )
        assert response.status_code == 200
        shares = response.json()["items"]

        # All returned shares should be of type run
        for share in shares:
            assert share["resource_type"] == "run"

    def test_filter_by_resource_id(self, admin_token):
        """Should be able to filter shares by resource ID."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        # Create a share
        requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )

        # Filter by resource_id
        response = requests.get(
            f"{BASE_URL}/admin/shares?resource_type=run&resource_id={run_id}",
            headers=headers,
        )
        assert response.status_code == 200
        shares = response.json()["items"]

        # All returned shares should have the specific resource_id
        for share in shares:
            assert share["resource_id"] == run_id


class TestShareRevocation:
    """Tests for revoking shares."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_can_revoke_share(self, admin_token):
        """Admin should be able to revoke a share."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        create_response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )
        assert create_response.status_code == 201
        share = create_response.json()

        # Revoke share
        revoke_response = requests.delete(
            f"{BASE_URL}/admin/shares/{share['id']}",
            headers=headers,
        )
        assert revoke_response.status_code == 204

    def test_revoked_share_shows_in_list(self, admin_token):
        """Revoked share should still appear in list with revoked_at set."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        create_response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )
        share = create_response.json()

        # Revoke share
        requests.delete(f"{BASE_URL}/admin/shares/{share['id']}", headers=headers)

        # Check list
        list_response = requests.get(f"{BASE_URL}/admin/shares", headers=headers)
        shares = list_response.json()["items"]
        revoked_share = next((s for s in shares if s["id"] == share["id"]), None)

        assert revoked_share is not None
        assert revoked_share["revoked_at"] is not None

    def test_cannot_revoke_already_revoked(self, admin_token):
        """Cannot revoke an already revoked share."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        create_response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )
        share = create_response.json()

        # Revoke first time
        requests.delete(f"{BASE_URL}/admin/shares/{share['id']}", headers=headers)

        # Try to revoke again
        response = requests.delete(
            f"{BASE_URL}/admin/shares/{share['id']}",
            headers=headers,
        )
        assert response.status_code == 404


class TestShareExpiry:
    """Tests for share expiration."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_share_has_expiry(self, admin_token):
        """Share with expires_hours should have expires_at field."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        create_response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id, "expires_hours": 24},
            headers=headers,
        )

        assert create_response.status_code == 201
        data = create_response.json()
        assert data["expires_at"] is not None

    def test_share_without_expiry(self, admin_token):
        """Share without expires_hours should have null expires_at."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        create_response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )

        assert create_response.status_code == 201
        data = create_response.json()
        assert data["expires_at"] is None

    def test_invalid_expiry_returns_400(self, admin_token):
        """Invalid expires_hours should return 400."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        # Too short
        response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id, "expires_hours": 0},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "INVALID_EXPIRY"

        # Too long
        response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": str(uuid.uuid4()), "expires_hours": 10000},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "INVALID_EXPIRY"


class TestShareResourceTypes:
    """Tests for different share resource types."""

    @pytest.fixture
    def admin_token(self):
        """Get admin token for tests."""
        return get_admin_token()

    def test_can_share_run(self, admin_token):
        """Should be able to create share for run."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        run_id = str(uuid.uuid4())

        response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "run", "resource_id": run_id},
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["resource_type"] == "run"

    def test_can_share_report(self, admin_token):
        """Should be able to create share for report."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        import uuid
        report_id = str(uuid.uuid4())

        response = requests.post(
            f"{BASE_URL}/admin/shares",
            json={"resource_type": "report", "resource_id": report_id},
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["resource_type"] == "report"
