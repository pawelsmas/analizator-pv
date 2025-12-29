"""
Contract tests for objective_used field in sizing response.

These tests verify:
- objective_used is present in response
- objective_used defaults to 'npv' when no optimization config
- objective_used reflects the requested objective
"""
import pytest
import requests


class TestObjectiveUsedPresence:
    """Test that objective_used is present in response."""

    def test_objective_used_present_in_response(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """objective_used should be present in response."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # objective_used should be present
        assert "objective_used" in data, "objective_used must be in response"
        assert data["objective_used"] is not None, "objective_used cannot be null"
        assert isinstance(data["objective_used"], str)


class TestObjectiveUsedDefault:
    """Test that objective_used defaults to 'npv'."""

    def test_default_objective_is_npv(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Default objective should be 'npv' when no optimization config."""
        # Ensure no optimization config in request
        request = {**minimal_sizing_request}
        if "optimization" in request:
            del request["optimization"]

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        objective = data.get("objective_used")

        assert objective == "npv", (
            f"Default objective should be 'npv', got '{objective}'"
        )


class TestObjectiveUsedWithConfig:
    """Test that objective_used reflects requested objective."""

    def test_objective_used_matches_request_npv(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """objective_used should match requested objective (npv)."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "npv"}
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        objective = data.get("objective_used")

        assert objective == "npv", (
            f"objective_used should be 'npv', got '{objective}'"
        )

    def test_objective_used_matches_request_payback(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """objective_used should match requested objective (payback)."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "payback"}
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:500]}"
        )

        data = response.json()
        objective = data.get("objective_used")

        assert objective == "payback", (
            f"objective_used should be 'payback', got '{objective}'"
        )


class TestObjectiveUsedValidValues:
    """Test that objective_used has valid values."""

    def test_objective_used_is_valid_enum(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """objective_used should be one of the valid enum values."""
        valid_objectives = {
            "npv",
            "payback",
            "self_consumption",
            "peak_reduction",
            "efc_utilization",
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        objective = data.get("objective_used")

        assert objective in valid_objectives, (
            f"objective_used '{objective}' not in valid values: {valid_objectives}"
        )
