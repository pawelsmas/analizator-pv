"""
Contract tests for Share v2 access enforcement (v3.8.0).

Tests:
- Password-protected shares
- Single-use shares
- Max access count enforcement
- Access tracking (access_count, last_access_at)
- Error codes for access denial
"""

import os
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

# Add bess-dispatch to path for auth_store
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))

BESS_DISPATCH_URL = os.getenv("BESS_DISPATCH_URL", "http://localhost:8031")
API_BASE = f"{BESS_DISPATCH_URL}/api/bess-dispatch"


@pytest.fixture(scope="module")
def auth_headers():
    """Get auth headers for admin access (assumes dev seed admin)."""
    # Login as dev admin
    resp = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": "admin@local", "password": "admin"},
    )
    if resp.status_code != 200:
        pytest.skip("Auth not available or dev seed not enabled")
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def test_run_id(auth_headers):
    """Create a test run and return its ID."""
    # Create a simple sizing run
    resp = requests.post(
        f"{BESS_DISPATCH_URL}/sizing",
        json={
            "load_kw": [100.0] * 24,
            "pv_generation_kw": [50.0] * 24,
            "mode": "pv_surplus",
            "durations_h": [1.0],
            "interval_minutes": 60,
            "discount_rate": 0.08,
            "analysis_years": 10,
            "capex_pln_per_kwh": 1500.0,
            "tariff_type": "flat",
            "flat_rate_pln_mwh": 400.0,
        },
        headers=auth_headers,
    )
    if resp.status_code not in (200, 201):
        pytest.skip("Cannot create test run")
    return resp.json().get("id", str(uuid.uuid4()))


class TestShareV2Create:
    """Tests for creating shares with v3.8.0 options."""

    def test_create_share_with_password(self, auth_headers, test_run_id):
        """Creating share with requires_password=true and valid password succeeds."""
        resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "label": "password protected",
                "requires_password": True,
                "password": "secret12345",  # 11 chars, >= 10 required
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["requires_password"] is True
        assert "token" in data
        assert "password_hash" not in str(data)  # Password hash should not be exposed

    def test_create_share_password_too_short(self, auth_headers, test_run_id):
        """Creating share with password < 10 chars fails with SHARE_PASSWORD_TOO_WEAK."""
        resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "requires_password": True,
                "password": "short",  # Only 5 chars
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["error_code"] == "SHARE_PASSWORD_TOO_WEAK"

    def test_create_share_password_required_but_missing(self, auth_headers, test_run_id):
        """Creating share with requires_password=true but no password fails."""
        resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "requires_password": True,
                # password missing
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["error_code"] == "SHARE_PASSWORD_REQUIRED"

    def test_create_share_single_use(self, auth_headers, test_run_id):
        """Creating single-use share succeeds."""
        resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "label": "single use",
                "single_use": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["single_use"] is True
        assert data["access_count"] == 0

    def test_create_share_max_access(self, auth_headers, test_run_id):
        """Creating share with max_access_count succeeds."""
        resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "label": "limited access",
                "max_access_count": 5,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["max_access_count"] == 5
        assert data["access_count"] == 0

    def test_create_share_invalid_max_access(self, auth_headers, test_run_id):
        """Creating share with max_access_count < 1 fails."""
        resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "max_access_count": 0,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["error_code"] == "INVALID_MAX_ACCESS_COUNT"


class TestShareV2ListResponse:
    """Tests for list_shares returning v3.8.0 fields."""

    def test_list_shares_includes_v2_fields(self, auth_headers, test_run_id):
        """List shares includes v3.8.0 fields."""
        # Create a share first
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "requires_password": True,
                "password": "password1234",
                "single_use": True,
                "max_access_count": 10,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        share_id = create_resp.json()["id"]

        # List shares
        resp = requests.get(f"{API_BASE}/shares", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        # Find our share
        share = next((s for s in data["items"] if s["id"] == share_id), None)
        assert share is not None

        # Check v3.8.0 fields are present
        assert "requires_password" in share
        assert share["requires_password"] is True
        assert "single_use" in share
        assert share["single_use"] is True
        assert "max_access_count" in share
        assert share["max_access_count"] == 10
        assert "access_count" in share
        assert "token_version" in share


class TestSharedAccessPasswordProtection:
    """Tests for password-protected share access."""

    def test_access_password_share_without_password(self, auth_headers, test_run_id):
        """Accessing password-protected share without password returns 401 SHARE_PASSWORD_REQUIRED."""
        # Create password-protected share
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "requires_password": True,
                "password": "secretpass10",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        # Try to access without password
        resp = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={"X-Share-Token": token},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["detail"]["error_code"] == "SHARE_PASSWORD_REQUIRED"

    def test_access_password_share_with_wrong_password(self, auth_headers, test_run_id):
        """Accessing password-protected share with wrong password returns 401 SHARE_PASSWORD_INVALID."""
        # Create password-protected share
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "requires_password": True,
                "password": "correctpassword",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        # Try to access with wrong password
        resp = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={
                "X-Share-Token": token,
                "X-Share-Password": "wrongpassword",
            },
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["detail"]["error_code"] == "SHARE_PASSWORD_INVALID"

    def test_access_password_share_with_correct_password(self, auth_headers, test_run_id):
        """Accessing password-protected share with correct password succeeds."""
        password = "mysecretpass"

        # Create password-protected share
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "requires_password": True,
                "password": password,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        # Access with correct password
        resp = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={
                "X-Share-Token": token,
                "X-Share-Password": password,
            },
        )
        assert resp.status_code == 200


class TestSharedAccessSingleUse:
    """Tests for single-use share access."""

    def test_single_use_share_first_access_succeeds(self, auth_headers, test_run_id):
        """First access to single-use share succeeds."""
        # Create single-use share
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "single_use": True,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        # First access should succeed
        resp = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={"X-Share-Token": token},
        )
        assert resp.status_code == 200

    def test_single_use_share_second_access_fails(self, auth_headers, test_run_id):
        """Second access to single-use share returns 409 SHARE_ALREADY_USED."""
        # Create single-use share
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "single_use": True,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        # First access
        resp1 = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={"X-Share-Token": token},
        )
        assert resp1.status_code == 200

        # Second access should fail
        resp2 = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={"X-Share-Token": token},
        )
        # Token is revoked so it's not found
        assert resp2.status_code in (401, 409)
        data = resp2.json()
        assert data["detail"]["error_code"] in ("SHARE_NOT_FOUND", "SHARE_ALREADY_USED")


class TestSharedAccessMaxCount:
    """Tests for max access count enforcement."""

    def test_max_access_count_enforced(self, auth_headers, test_run_id):
        """Access is denied after max_access_count is reached."""
        max_count = 2

        # Create share with max_access_count=2
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "max_access_count": max_count,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        # First 2 accesses should succeed
        for i in range(max_count):
            resp = requests.get(
                f"{API_BASE}/shared/runs/{test_run_id}",
                headers={"X-Share-Token": token},
            )
            assert resp.status_code == 200, f"Access {i+1} failed"

        # Third access should fail
        resp = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={"X-Share-Token": token},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["detail"]["error_code"] == "SHARE_MAX_ACCESS_EXCEEDED"


class TestSharedAccessTracking:
    """Tests for access count tracking."""

    def test_access_count_increments(self, auth_headers, test_run_id):
        """access_count increments with each access."""
        # Create share
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
                "max_access_count": 10,  # Allow multiple accesses
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]
        share_id = create_resp.json()["id"]

        # Access the share 3 times
        for _ in range(3):
            resp = requests.get(
                f"{API_BASE}/shared/runs/{test_run_id}",
                headers={"X-Share-Token": token},
            )
            assert resp.status_code == 200

        # Check access_count in list
        list_resp = requests.get(f"{API_BASE}/shares", headers=auth_headers)
        assert list_resp.status_code == 200
        share = next((s for s in list_resp.json()["items"] if s["id"] == share_id), None)
        assert share is not None
        assert share["access_count"] == 3
        assert share["last_access_at"] is not None


class TestSharedAccessInvalidToken:
    """Tests for invalid share token handling."""

    def test_invalid_token_returns_401(self, test_run_id):
        """Invalid token returns 401 SHARE_NOT_FOUND."""
        resp = requests.get(
            f"{API_BASE}/shared/runs/{test_run_id}",
            headers={"X-Share-Token": "invalid_token_12345"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["detail"]["error_code"] == "SHARE_NOT_FOUND"

    def test_missing_token_returns_422(self, test_run_id):
        """Missing X-Share-Token header returns 422."""
        resp = requests.get(f"{API_BASE}/shared/runs/{test_run_id}")
        assert resp.status_code == 422  # FastAPI validation error


class TestSharedAccessResourceMismatch:
    """Tests for resource mismatch handling."""

    def test_wrong_run_id_returns_403(self, auth_headers, test_run_id):
        """Accessing different run_id with share token returns 403 RESOURCE_MISMATCH."""
        # Create share for test_run_id
        create_resp = requests.post(
            f"{API_BASE}/shares",
            json={
                "resource_type": "run",
                "resource_id": test_run_id,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        # Try to access different run_id
        resp = requests.get(
            f"{API_BASE}/shared/runs/different_run_id_12345",
            headers={"X-Share-Token": token},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["error_code"] == "RESOURCE_MISMATCH"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
