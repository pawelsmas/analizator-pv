"""
Contract tests for step limit enforcement (v2.5.0 PR1).

Tests verify:
- Requests exceeding MAX_STEPS return 422
- Error response includes error_code=STEPS_LIMIT_EXCEEDED
- Error response includes max_steps and steps fields
"""

import pytest
import os
from ._api import post_json, DEFAULT_BASE_URL
import requests


# Set a small MAX_STEPS for testing
TEST_MAX_STEPS = 100


def _base_req_with_steps(n_steps: int):
    """Create a sizing request with specified number of steps."""
    return {
        "load_kw": [100.0] * n_steps,
        "pv_generation_kw": [50.0] * n_steps,
        "mode": "pv_surplus",
        "durations_h": [1.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


class TestStepLimitEnforcement:
    """Tests for MAX_STEPS limit enforcement."""

    def test_request_within_limit_succeeds(self):
        """Request with steps within limit should succeed."""
        # Default MAX_STEPS is 35040, so 24 steps should be fine
        request = _base_req_with_steps(24)
        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )
        # Should succeed (200) or at most validation error (400/422)
        # but not 422 with STEPS_LIMIT_EXCEEDED
        if resp.status_code == 422:
            data = resp.json()
            assert data.get("error_code") != "STEPS_LIMIT_EXCEEDED"
        else:
            assert resp.status_code in (200, 400)

    def test_large_request_returns_422(self):
        """Very large request should return 422 with error_code."""
        # Create a request with more steps than default MAX_STEPS (35040)
        # This would be a full year at 15-min resolution + extra
        n_steps = 40000
        request = _base_req_with_steps(n_steps)

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )

        assert resp.status_code == 422
        data = resp.json()
        assert data.get("error_code") == "STEPS_LIMIT_EXCEEDED"
        assert "max_steps" in data
        assert "steps" in data
        assert data["steps"] == n_steps

    def test_error_response_structure(self):
        """Error response should have correct structure."""
        n_steps = 50000
        request = _base_req_with_steps(n_steps)

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )

        assert resp.status_code == 422
        data = resp.json()

        # Check all required fields
        assert "error_code" in data
        assert "detail" in data
        assert "max_steps" in data
        assert "steps" in data

        # Check types
        assert isinstance(data["error_code"], str)
        assert isinstance(data["detail"], str)
        assert isinstance(data["max_steps"], int)
        assert isinstance(data["steps"], int)

    def test_error_detail_is_descriptive(self):
        """Error detail should describe the issue."""
        n_steps = 45000
        request = _base_req_with_steps(n_steps)

        resp = requests.post(
            f"{DEFAULT_BASE_URL}/sizing",
            json=request,
        )

        assert resp.status_code == 422
        data = resp.json()

        # Detail should mention steps and limit
        detail = data["detail"]
        assert str(n_steps) in detail
        assert "exceed" in detail.lower() or "maximum" in detail.lower()


class TestLimitsEndpoint:
    """Tests for GET /api/bess-dispatch/limits endpoint."""

    def test_limits_endpoint_returns_200(self):
        """Limits endpoint should return 200."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/api/bess-dispatch/limits")
        assert resp.status_code == 200

    def test_limits_endpoint_returns_max_steps(self):
        """Limits endpoint should return max_steps."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/api/bess-dispatch/limits")
        data = resp.json()

        assert "max_steps" in data
        assert isinstance(data["max_steps"], int)
        assert data["max_steps"] > 0

    def test_limits_endpoint_returns_max_request_bytes(self):
        """Limits endpoint should return max_request_bytes."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/api/bess-dispatch/limits")
        data = resp.json()

        assert "max_request_bytes" in data
        assert isinstance(data["max_request_bytes"], int)
        assert data["max_request_bytes"] > 0

    def test_limits_endpoint_returns_all_limits(self):
        """Limits endpoint should return all configured limits."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/api/bess-dispatch/limits")
        data = resp.json()

        expected_keys = [
            "max_request_bytes",
            "max_steps",
            "max_variants",
            "max_durations",
            "max_trace_steps",
            "default_preview_rows",
        ]

        for key in expected_keys:
            assert key in data, f"Missing key: {key}"
