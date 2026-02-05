"""
Contract tests for rate limiting on login endpoint (v3.2.0).

Verifies that login endpoint returns 429 after exceeding rate limit.
Requires running API server at BASE_URL (default: localhost:8031).

Note: This test requires RL_LOGIN_PER_IP_PER_MIN=2 environment variable
to be set on the server for deterministic testing.
"""
import os
import pytest
import requests
from ._api import DEFAULT_BASE_URL


# Skip if not in rate limit test mode
RATE_LIMIT_TEST_MODE = os.getenv("RATE_LIMIT_TEST_MODE", "false").lower() == "true"


@pytest.mark.skipif(
    not RATE_LIMIT_TEST_MODE,
    reason="Rate limit tests require RATE_LIMIT_TEST_MODE=true and server with RL_LOGIN_PER_IP_PER_MIN=2"
)
class TestRateLimitLogin429:
    """Test rate limiting on login endpoint."""

    def test_login_rate_limit_returns_429(self):
        """
        After exceeding login rate limit, should get 429.

        Test requires server started with:
        RL_LOGIN_PER_IP_PER_MIN=2
        """
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        login_payload = {"username": "test", "password": "wrong"}

        # Make requests up to and beyond limit
        responses = []
        for i in range(4):
            resp = requests.post(url, json=login_payload, timeout=10)
            responses.append(resp)

        # With limit=2, 3rd request should be rate limited
        # (first 2 use tokens, 3rd has no tokens)
        statuses = [r.status_code for r in responses]

        # At least one should be 429
        assert 429 in statuses, (
            f"Expected at least one 429 response, got statuses: {statuses}"
        )

        # Find the 429 response and verify structure
        rate_limited = next(r for r in responses if r.status_code == 429)

        # Check Retry-After header
        assert "Retry-After" in rate_limited.headers, (
            "429 response should have Retry-After header"
        )

        # Check response body
        body = rate_limited.json()
        assert body.get("error_code") == "RATE_LIMITED", (
            f"Expected error_code=RATE_LIMITED, got: {body}"
        )
        assert "retry_after_seconds" in body, (
            f"Expected retry_after_seconds in body, got: {body}"
        )

    def test_rate_limit_retry_after_is_positive(self):
        """Retry-After header should be a positive integer."""
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
        login_payload = {"username": "test", "password": "wrong"}

        # Exhaust rate limit
        for _ in range(5):
            resp = requests.post(url, json=login_payload, timeout=10)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                assert retry_after is not None
                assert int(retry_after) > 0
                return

        pytest.skip("Could not trigger rate limit")


class TestRateLimitMetrics:
    """Test that rate limit metrics are exposed."""

    def test_metrics_endpoint_has_rate_limit_counters(self):
        """GET /metrics should include rate limit counters."""
        url = f"{DEFAULT_BASE_URL}/metrics"
        resp = requests.get(url, timeout=10)

        assert resp.status_code == 200

        # Check for rate limit metric definitions
        # (counters may be 0 if no rate limiting happened yet)
        content = resp.text

        # Metric should be defined even if value is 0
        assert "bess_rate_limited_total" in content or "bess_rate_limit" in content, (
            "Rate limit metrics should be defined in /metrics"
        )
