"""
Contract tests for deprecations endpoint (v2.6.0 PR4).

Tests verify:
- GET /api/bess-dispatch/deprecations returns 200
- Response contains version, last_updated, items
- Each item has required fields
- Items have valid status values
- Endpoint is documented in OpenAPI
"""

import pytest
import requests
from ._api import DEFAULT_BASE_URL


def _get_deprecations():
    """Fetch deprecations from the endpoint."""
    url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/deprecations"
    resp = requests.get(url)
    return resp


class TestDeprecationsEndpoint:
    """Tests for GET /api/bess-dispatch/deprecations."""

    def test_deprecations_returns_200(self):
        """Deprecations endpoint should return 200."""
        resp = _get_deprecations()
        assert resp.status_code == 200

    def test_deprecations_returns_json(self):
        """Deprecations endpoint should return JSON."""
        resp = _get_deprecations()
        assert resp.headers.get("content-type", "").startswith("application/json")

    def test_deprecations_has_version(self):
        """Response should have version field."""
        resp = _get_deprecations()
        data = resp.json()
        assert "version" in data
        assert isinstance(data["version"], str)

    def test_deprecations_has_last_updated(self):
        """Response should have last_updated field."""
        resp = _get_deprecations()
        data = resp.json()
        assert "last_updated" in data
        assert isinstance(data["last_updated"], str)

    def test_deprecations_has_items(self):
        """Response should have items array."""
        resp = _get_deprecations()
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_deprecations_items_have_required_fields(self):
        """Each item should have all required fields."""
        resp = _get_deprecations()
        data = resp.json()

        required_fields = [
            "field",
            "location",
            "status",
            "since",
            "remove_in",
            "replacement",
            "notes",
        ]

        for item in data["items"]:
            for field in required_fields:
                assert field in item, f"Item missing field: {field}"

    def test_deprecations_items_have_valid_status(self):
        """Each item should have valid status value."""
        resp = _get_deprecations()
        data = resp.json()

        valid_statuses = ["deprecated", "removed", "warning"]

        for item in data["items"]:
            assert item["status"] in valid_statuses, \
                f"Invalid status: {item['status']}"

    def test_deprecations_items_have_version_format(self):
        """since and remove_in should be version strings."""
        resp = _get_deprecations()
        data = resp.json()

        for item in data["items"]:
            # Should start with 'v' and contain a dot
            assert item["since"].startswith("v"), \
                f"since should start with 'v': {item['since']}"
            assert "." in item["since"], \
                f"since should be semver: {item['since']}"
            assert item["remove_in"].startswith("v"), \
                f"remove_in should start with 'v': {item['remove_in']}"


class TestDeprecationsRegistry:
    """Tests for the deprecations registry content."""

    def test_registry_has_items(self):
        """Registry should have at least one deprecation."""
        resp = _get_deprecations()
        data = resp.json()
        assert len(data["items"]) >= 1, "Registry should have deprecations"

    def test_registry_export_revenue_deprecated(self):
        """export_revenue_pln should be in the registry."""
        resp = _get_deprecations()
        data = resp.json()

        fields = [item["field"] for item in data["items"]]
        assert "export_revenue_pln" in fields, \
            "export_revenue_pln should be deprecated"

    def test_registry_fields_are_unique(self):
        """Each field should appear only once."""
        resp = _get_deprecations()
        data = resp.json()

        fields = [item["field"] for item in data["items"]]
        assert len(fields) == len(set(fields)), "Duplicate fields in registry"


class TestDeprecationsOpenAPI:
    """Tests for OpenAPI documentation."""

    def test_deprecations_in_openapi(self):
        """Deprecations endpoint should be in OpenAPI spec."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/openapi.json")
        assert resp.status_code == 200

        spec = resp.json()
        paths = spec.get("paths", {})

        # Check endpoint is documented
        assert "/api/bess-dispatch/deprecations" in paths, \
            "Deprecations endpoint should be in OpenAPI"

    def test_deprecations_has_get_method(self):
        """Deprecations endpoint should have GET method documented."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/openapi.json")
        spec = resp.json()
        paths = spec.get("paths", {})

        endpoint = paths.get("/api/bess-dispatch/deprecations", {})
        assert "get" in endpoint, "Deprecations should support GET"

    def test_deprecations_response_schema_documented(self):
        """Deprecations response schema should be documented."""
        resp = requests.get(f"{DEFAULT_BASE_URL}/openapi.json")
        spec = resp.json()
        paths = spec.get("paths", {})

        endpoint = paths.get("/api/bess-dispatch/deprecations", {})
        get_op = endpoint.get("get", {})
        responses = get_op.get("responses", {})

        assert "200" in responses, "200 response should be documented"
