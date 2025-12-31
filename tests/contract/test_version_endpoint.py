"""
Contract tests for GET /api/bess-dispatch/version endpoint (v1.8.0).

Tests verify:
- Endpoint returns 200
- Response has all required fields
- Fields have correct types
"""
import pytest
import requests

BASE_URL = "http://localhost:8031"


class TestVersionEndpoint:
    """Contract tests for /version endpoint."""

    def test_version_endpoint_returns_200(self):
        """Verify /version endpoint returns 200."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")
        assert response.status_code == 200

    def test_version_has_service_field(self):
        """Verify response has service field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")
        data = response.json()

        assert "service" in data
        assert data["service"] == "bess-dispatch"

    def test_version_has_git_sha_field(self):
        """Verify response has git_sha field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")
        data = response.json()

        assert "git_sha" in data
        assert isinstance(data["git_sha"], str)
        assert len(data["git_sha"]) > 0

    def test_version_has_build_time_utc_field(self):
        """Verify response has build_time_utc field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")
        data = response.json()

        assert "build_time_utc" in data
        assert isinstance(data["build_time_utc"], str)
        assert len(data["build_time_utc"]) > 0

    def test_version_has_schema_version_field(self):
        """Verify response has schema_version field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")
        data = response.json()

        assert "schema_version" in data
        assert isinstance(data["schema_version"], str)
        # Schema version should be semantic version format
        parts = data["schema_version"].split(".")
        assert len(parts) == 3, "Schema version should be in X.Y.Z format"

    def test_version_has_assumptions_version_field(self):
        """Verify response has assumptions_version field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")
        data = response.json()

        assert "assumptions_version" in data
        assert isinstance(data["assumptions_version"], str)
        # Assumptions version should start with "v"
        assert data["assumptions_version"].startswith("v"), (
            f"Assumptions version should start with 'v', got '{data['assumptions_version']}'"
        )

    def test_version_all_fields_present(self):
        """Verify all required fields are present in single request."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")
        data = response.json()

        required_fields = [
            "service",
            "git_sha",
            "build_time_utc",
            "schema_version",
            "assumptions_version",
        ]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_version_content_type_json(self):
        """Verify response content type is JSON."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/version")

        assert "application/json" in response.headers.get("content-type", "")
