"""
Contract tests for GET /api/bess-dispatch/validation/packs endpoint (v1.7.0).

Tests:
- Response structure matches PackListResponse schema
- Returns list of available pack names
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


class TestValidationPacksList:
    """Contract tests for GET /validation/packs endpoint."""

    def test_get_validation_packs_returns_200(self):
        """GET /validation/packs should return 200 OK."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/validation/packs")
        assert response.status_code == 200

    def test_get_validation_packs_response_structure(self):
        """Response should have 'packs' field as list."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/validation/packs")
        data = response.json()

        assert "packs" in data
        assert isinstance(data["packs"], list)

    def test_get_validation_packs_items_are_strings(self):
        """Each pack name should be a string."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/validation/packs")
        data = response.json()

        for pack_name in data["packs"]:
            assert isinstance(pack_name, str)
            assert len(pack_name) > 0

    def test_baseline_pack_exists(self):
        """Baseline pack should be available."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/validation/packs")
        data = response.json()

        assert "baseline" in data["packs"], "baseline pack should exist"
