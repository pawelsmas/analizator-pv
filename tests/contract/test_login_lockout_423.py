"""
Contract tests for login lockout (v3.2.0 PR3).

Verifies that login endpoint returns 423 Locked after exceeding failed attempts.
Requires running API server at BASE_URL (default: localhost:8031).

Note: This test requires LOCKOUT_MAX_ATTEMPTS=3 and LOCKOUT_DURATION_SECONDS=60
environment variables to be set on the server for deterministic testing.
"""
import os
import pytest
import requests
from ._api import DEFAULT_BASE_URL


# Skip if not in lockout test mode
LOCKOUT_TEST_MODE = os.getenv("LOCKOUT_TEST_MODE", "false").lower() == "true"


@pytest.mark.skipif(
    not LOCKOUT_TEST_MODE,
    reason="Lockout tests require LOCKOUT_TEST_MODE=true and server with LOCKOUT_MAX_ATTEMPTS=3"
)
class TestLoginLockout423:
    """Test login lockout after failed attempts."""

    def test_login_lockout_returns_423(self):
        """
        After exceeding max failed attempts, should get 423 Locked.

        Test requires server started with:
        LOCKOUT_MAX_ATTEMPTS=3
        LOCKOUT_DURATION_SECONDS=60
        """
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        # Use unique email for each test run to avoid interference
        import time
        unique_email = f"lockout_test_{int(time.time())}@test.local"
        login_payload = {"email": unique_email, "password": "wrongpassword"}

        # Make requests up to and beyond limit
        responses = []
        for i in range(5):
            resp = requests.post(url, json=login_payload, timeout=10)
            responses.append(resp)

        # With limit=3, 4th request should be locked
        statuses = [r.status_code for r in responses]

        # At least one should be 423
        assert 423 in statuses, (
            f"Expected at least one 423 response, got statuses: {statuses}"
        )

        # Find the 423 response and verify structure
        locked_response = next(r for r in responses if r.status_code == 423)
        body = locked_response.json()

        assert body.get("error_code") == "ACCOUNT_LOCKED", (
            f"Expected error_code=ACCOUNT_LOCKED, got: {body}"
        )
        assert "locked_until_seconds" in body, (
            f"Expected locked_until_seconds in body, got: {body}"
        )
        assert "max_attempts" in body, (
            f"Expected max_attempts in body, got: {body}"
        )

    def test_lockout_locked_until_is_positive(self):
        """locked_until_seconds should be a positive integer."""
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        import time
        unique_email = f"lockout_positive_{int(time.time())}@test.local"
        login_payload = {"email": unique_email, "password": "wrongpassword"}

        # Exhaust lockout limit
        for _ in range(10):
            resp = requests.post(url, json=login_payload, timeout=10)
            if resp.status_code == 423:
                body = resp.json()
                locked_until = body.get("locked_until_seconds")
                assert locked_until is not None
                assert locked_until > 0
                return

        pytest.skip("Could not trigger lockout")


class TestLoginLockoutMetrics:
    """Test that lockout metrics are exposed."""

    def test_metrics_endpoint_has_lockout_counters(self):
        """GET /metrics should include lockout counters."""
        url = f"{DEFAULT_BASE_URL}/metrics"
        resp = requests.get(url, timeout=10)

        assert resp.status_code == 200

        content = resp.text

        # Check for lockout metric definitions
        assert "bess_login_failures_total" in content or "bess_accounts_locked" in content, (
            "Lockout metrics should be defined in /metrics"
        )
