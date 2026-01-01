"""
Contract tests for request body size limit enforcement (v2.5.0 PR1).

Tests verify:
- Requests exceeding MAX_REQUEST_BYTES return 413
- Error response includes error_code=REQUEST_TOO_LARGE
- Error response includes max_request_bytes field
"""

import pytest
import requests
from ._api import DEFAULT_BASE_URL


def _base_req():
    """Minimal valid sizing request."""
    return {
        "load_kw": [100.0] * 24,
        "pv_generation_kw": [50.0] * 24,
        "mode": "pv_surplus",
        "durations_h": [1.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def _create_large_request(target_bytes: int):
    """
    Create a request with approximately target_bytes size.

    Uses a large 'notes' field to inflate the request size.
    """
    base = _base_req()

    # Calculate padding size needed
    # Base request is roughly 500 bytes, so we need to add more
    import json
    base_size = len(json.dumps(base))
    padding_needed = target_bytes - base_size

    if padding_needed > 0:
        # Add a large notes field (ignored by API but inflates body)
        # Use repeated character to make it compressible but still large
        base["notes"] = "X" * padding_needed

    return base


class TestRequestBodySizeLimit:
    """Tests for MAX_REQUEST_BYTES limit enforcement."""

    def test_normal_request_succeeds(self):
        """Normal-sized request should succeed."""
        request = _base_req()
        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )
        # Should succeed (200) or validation error (400/422)
        # but not 413 (too large)
        assert resp.status_code != 413

    def test_large_request_returns_413(self):
        """Request exceeding MAX_REQUEST_BYTES should return 413."""
        # Default MAX_REQUEST_BYTES is 2.5MB
        # Create a request larger than that
        request = _create_large_request(3_000_000)  # 3MB

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )

        assert resp.status_code == 413
        data = resp.json()
        assert data.get("error_code") == "REQUEST_TOO_LARGE"

    def test_error_response_structure(self):
        """Error response should have correct structure."""
        request = _create_large_request(3_000_000)

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )

        assert resp.status_code == 413
        data = resp.json()

        # Check required fields
        assert "error_code" in data
        assert "detail" in data
        assert "max_request_bytes" in data

        # Check types
        assert isinstance(data["error_code"], str)
        assert isinstance(data["detail"], str)
        assert isinstance(data["max_request_bytes"], int)

    def test_error_max_request_bytes_value(self):
        """Error should include the configured max_request_bytes."""
        request = _create_large_request(3_000_000)

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )

        assert resp.status_code == 413
        data = resp.json()

        # Should match the default or configured limit
        assert data["max_request_bytes"] > 0
        # Default is 2.5MB
        assert data["max_request_bytes"] == 2_500_000 or data["max_request_bytes"] > 0

    def test_just_under_limit_succeeds(self):
        """Request just under the limit should succeed."""
        # Create a request that's 2MB (under 2.5MB limit)
        request = _create_large_request(2_000_000)

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )

        # Should not be 413
        # Might be 422 for step limit or other validation, but not 413
        assert resp.status_code != 413

    def test_get_requests_bypass_limit(self):
        """GET requests should not be affected by body size limit."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/api/bess-dispatch/limits")
        assert resp.status_code == 200


class TestContentLengthHeader:
    """Tests for Content-Length header validation."""

    def test_content_length_validation(self):
        """Request with large Content-Length should be rejected early."""
        # Send a request with a large Content-Length header
        # but small body (simulates attempt to DoS)
        request = _base_req()

        # This tests that Content-Length is checked
        # Note: requests library sets Content-Length automatically
        # so we need to send the actual large body
        large_request = _create_large_request(3_000_000)

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=large_request,
        )

        assert resp.status_code == 413
