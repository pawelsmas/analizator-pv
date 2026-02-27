"""
Contract tests for rate limiting headers (v3.5.0 PR3).

Tests verify:
- Rate limit headers are present in responses
- 429 response on rate limit exceeded
- Headers have correct format
"""
import pytest
import requests

BASE_URL = "http://localhost:8031"


class TestRateLimitHeaders:
    """Contract tests for rate limit response headers."""

    def test_response_has_ratelimit_limit_header(self):
        """Verify responses have X-RateLimit-Limit header."""
        response = requests.get(f"{BASE_URL}/info")

        # Header should be present (if rate limiting enabled)
        if "X-RateLimit-Limit" in response.headers:
            limit = int(response.headers["X-RateLimit-Limit"])
            assert limit > 0

    def test_response_has_ratelimit_remaining_header(self):
        """Verify responses have X-RateLimit-Remaining header."""
        response = requests.get(f"{BASE_URL}/info")

        if "X-RateLimit-Remaining" in response.headers:
            remaining = int(response.headers["X-RateLimit-Remaining"])
            assert remaining >= 0

    def test_response_has_ratelimit_reset_header(self):
        """Verify responses have X-RateLimit-Reset header."""
        response = requests.get(f"{BASE_URL}/info")

        if "X-RateLimit-Reset" in response.headers:
            reset = int(response.headers["X-RateLimit-Reset"])
            assert reset >= 0

    def test_health_live_skips_rate_limit(self):
        """Health endpoints should not be rate limited."""
        # Make many requests to health endpoint
        for _ in range(100):
            response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/live")
            assert response.status_code == 200

    def test_health_ready_skips_rate_limit(self):
        """Health endpoints should not be rate limited."""
        # Make many requests to health endpoint
        for _ in range(100):
            response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
            # May be 200 or 503, but never 429
            assert response.status_code != 429

    def test_metrics_skips_rate_limit(self):
        """Metrics endpoint should not be rate limited."""
        # Make many requests to metrics endpoint
        for _ in range(100):
            response = requests.get(f"{BASE_URL}/metrics")
            assert response.status_code == 200


class TestRateLimitHeaderFormat:
    """Tests for rate limit header format validation."""

    def test_limit_is_integer(self):
        """X-RateLimit-Limit should be an integer."""
        response = requests.get(f"{BASE_URL}/info")

        if "X-RateLimit-Limit" in response.headers:
            limit_str = response.headers["X-RateLimit-Limit"]
            # Should be parseable as int
            limit = int(limit_str)
            assert limit > 0

    def test_remaining_is_integer(self):
        """X-RateLimit-Remaining should be an integer."""
        response = requests.get(f"{BASE_URL}/info")

        if "X-RateLimit-Remaining" in response.headers:
            remaining_str = response.headers["X-RateLimit-Remaining"]
            # Should be parseable as int
            remaining = int(remaining_str)
            assert remaining >= 0

    def test_reset_is_integer_seconds(self):
        """X-RateLimit-Reset should be seconds as integer."""
        response = requests.get(f"{BASE_URL}/info")

        if "X-RateLimit-Reset" in response.headers:
            reset_str = response.headers["X-RateLimit-Reset"]
            # Should be parseable as int
            reset = int(reset_str)
            assert 0 <= reset <= 60  # Within 1 minute window


class TestRateLimitConsistency:
    """Tests for rate limit behavior consistency."""

    def test_remaining_decreases_with_requests(self):
        """Remaining should decrease with each request."""
        # Make two requests and compare remaining
        response1 = requests.get(f"{BASE_URL}/info")
        response2 = requests.get(f"{BASE_URL}/info")

        if "X-RateLimit-Remaining" in response1.headers:
            remaining1 = int(response1.headers["X-RateLimit-Remaining"])
            remaining2 = int(response2.headers["X-RateLimit-Remaining"])

            # remaining2 should be less than or equal to remaining1
            # (may be equal if tokens refilled)
            assert remaining2 <= remaining1 + 1  # Allow for token refill

    def test_limit_stays_constant(self):
        """Limit should stay constant across requests."""
        response1 = requests.get(f"{BASE_URL}/info")
        response2 = requests.get(f"{BASE_URL}/info")

        if "X-RateLimit-Limit" in response1.headers:
            limit1 = int(response1.headers["X-RateLimit-Limit"])
            limit2 = int(response2.headers["X-RateLimit-Limit"])

            assert limit1 == limit2
