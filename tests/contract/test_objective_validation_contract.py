"""
Contract tests for objective validation in sizing request.

These tests verify:
- Default objective is 'npv' when not specified
- Valid objective values are accepted (npv, payback, etc.)
- Invalid objective values return 422 validation error
"""
import pytest
import requests


VALID_OBJECTIVES = {
    "npv",
    "payback",
    "self_consumption",
    "peak_reduction",
    "efc_utilization",
}


class TestObjectiveDefaultValue:
    """Test that default objective is 'npv'."""

    def test_objective_default_is_npv(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When no optimization config, objective_used should be 'npv'."""
        # Ensure no optimization config
        request = {**minimal_sizing_request}
        if "optimization" in request:
            del request["optimization"]

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        assert data.get("objective_used") == "npv", (
            f"Default objective should be 'npv', got '{data.get('objective_used')}'"
        )


class TestObjectiveValidValues:
    """Test that valid objective values are accepted."""

    @pytest.mark.parametrize("objective", sorted(VALID_OBJECTIVES))
    def test_valid_objective_accepted(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
        objective,
    ):
        """Valid objective values should be accepted (200 OK)."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": objective}
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200, (
            f"Expected 200 for objective='{objective}', "
            f"got {response.status_code}: {response.text[:300]}"
        )

        data = response.json()
        assert data.get("objective_used") == objective, (
            f"objective_used should be '{objective}', got '{data.get('objective_used')}'"
        )


class TestObjectiveInvalidValues:
    """Test that invalid objective values return 422 validation error."""

    def test_invalid_objective_returns_422(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Invalid objective value should return 422."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "invalid_objective"}
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 422, (
            f"Expected 422 for invalid objective, got {response.status_code}"
        )

    def test_invalid_objective_typo_returns_422(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Common typo (npvv instead of npv) should return 422."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "npvv"}  # Typo
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 422, (
            f"Expected 422 for typo 'npvv', got {response.status_code}"
        )

    def test_uppercase_objective_returns_422(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Uppercase objective (NPV instead of npv) should return 422."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "NPV"}  # Uppercase
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 422, (
            f"Expected 422 for uppercase 'NPV', got {response.status_code}"
        )

    def test_empty_objective_returns_422(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Empty objective string should return 422."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": ""}
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 422, (
            f"Expected 422 for empty objective, got {response.status_code}"
        )


class TestObjectiveErrorMessage:
    """Test that error message is helpful."""

    def test_error_message_lists_valid_values(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Error message should list valid objective values."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "xyz"}
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 422
        error_text = response.text.lower()

        # Should mention at least one valid value
        assert "npv" in error_text or "valid" in error_text, (
            f"Error message should be helpful: {response.text[:500]}"
        )
