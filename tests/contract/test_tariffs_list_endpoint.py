"""
Contract tests for GET /api/bess-dispatch/tariffs endpoint (v2.1.0 PR2).

Tests verify:
- Endpoint returns 200 OK
- Response contains presets array
- pl_flat_2026 preset exists
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


class TestTariffsListEndpoint:
    """Tests for GET /tariffs endpoint."""

    def test_tariffs_list_returns_200(self):
        """Verify endpoint returns 200 OK."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/tariffs",
            timeout=30,
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_tariffs_list_response_structure(self):
        """Verify response has presets array."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/tariffs",
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        assert "presets" in result
        assert isinstance(result["presets"], list)

    def test_tariffs_list_presets_not_empty(self):
        """Verify presets array is not empty."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/tariffs",
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        assert len(result["presets"]) > 0, "Presets array should not be empty"

    def test_tariffs_list_preset_structure(self):
        """Verify each preset has id and label."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/tariffs",
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        for preset in result["presets"]:
            assert "id" in preset, "Preset should have 'id' field"
            assert "label" in preset, "Preset should have 'label' field"
            assert isinstance(preset["id"], str)
            assert isinstance(preset["label"], str)

    def test_pl_flat_2026_preset_exists(self):
        """Verify pl_flat_2026 preset is in the list."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/tariffs",
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        preset_ids = [p["id"] for p in result["presets"]]
        assert "pl_flat_2026" in preset_ids, "pl_flat_2026 preset should exist"

    def test_pl_flat_2026_has_correct_label(self):
        """Verify pl_flat_2026 has expected label."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/tariffs",
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        pl_flat = next((p for p in result["presets"] if p["id"] == "pl_flat_2026"), None)
        assert pl_flat is not None
        assert "PL" in pl_flat["label"] or "Flat" in pl_flat["label"]
