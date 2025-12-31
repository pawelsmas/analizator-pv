"""
Contract tests for POST /api/bess-dispatch/jobs/validate-pack endpoint (v1.7.0).

Tests:
- Response structure matches ValidatePackJobResponse schema
- wait=true returns completed job inline
- Result contains summary and scenarios
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


class TestJobsValidatePackWaitTrue:
    """Contract tests for POST /jobs/validate-pack with wait=true."""

    def test_validate_pack_returns_200(self):
        """POST /jobs/validate-pack should return 200 OK."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        assert response.status_code == 200

    def test_validate_pack_response_structure(self):
        """Response should have required fields."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        data = response.json()

        # Required fields
        assert "job_id" in data
        assert "type" in data
        assert "pack" in data
        assert "status" in data
        assert "items_total" in data
        assert "items_done" in data
        assert "error_count" in data

    def test_validate_pack_wait_true_status_done(self):
        """With wait=true, status should be 'done'."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        data = response.json()

        assert data["status"] == "done"
        assert data["type"] == "validate_pack"
        assert data["pack"] == "baseline"

    def test_validate_pack_result_contains_summary(self):
        """Result should contain summary with total/pass/fail counts."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        data = response.json()

        assert "result" in data
        result = data["result"]
        assert result is not None

        assert "summary" in result
        summary = result["summary"]
        assert "total" in summary
        assert "pass" in summary
        assert "fail" in summary

    def test_validate_pack_result_contains_scenarios(self):
        """Result should contain scenarios list."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        data = response.json()

        result = data["result"]
        assert "scenarios" in result
        assert isinstance(result["scenarios"], list)

    def test_validate_pack_scenario_structure(self):
        """Each scenario should have name and pass fields."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        data = response.json()

        result = data["result"]
        for scenario in result["scenarios"]:
            assert "name" in scenario
            assert "pass" in scenario
            assert isinstance(scenario["name"], str)
            assert isinstance(scenario["pass"], bool)

    def test_validate_pack_items_count_matches(self):
        """items_total and items_done should match scenario count."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "baseline", "wait": True},
            timeout=120,
        )
        data = response.json()

        result = data["result"]
        scenario_count = len(result["scenarios"])

        assert data["items_total"] == scenario_count
        assert data["items_done"] == scenario_count

    def test_validate_pack_invalid_pack_returns_404(self):
        """Invalid pack name should return 404."""
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
            json={"pack": "nonexistent_pack", "wait": True},
            timeout=30,
        )
        assert response.status_code == 404
