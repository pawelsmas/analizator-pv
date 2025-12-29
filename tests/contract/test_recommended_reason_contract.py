"""
Contract tests for recommended_reason field in sizing response.

These tests verify:
- recommended_reason is present when there are variants
- recommended_reason contains objective-specific information
- recommended_reason is human-readable (Polish)
"""
import pytest
import requests


class TestRecommendedReasonPresence:
    """Test that recommended_reason is present in response."""

    def test_recommended_reason_present_in_response(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason should be present when variants exist."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Should have variants
        assert len(data.get("variants", [])) > 0

        # recommended_reason should be present
        assert "recommended_reason" in data, "recommended_reason must be in response"
        assert data["recommended_reason"] is not None, "recommended_reason cannot be null"
        assert isinstance(data["recommended_reason"], str)
        assert len(data["recommended_reason"]) > 0, "recommended_reason cannot be empty"


class TestRecommendedReasonContent:
    """Test that recommended_reason contains relevant information."""

    def test_reason_mentions_npv_by_default(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Default objective is NPV, so reason should mention NPV."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        reason = data.get("recommended_reason", "")

        # Should mention NPV (Polish: Najwyższe NPV)
        assert "NPV" in reason, f"Reason should mention NPV: {reason}"

    def test_reason_contains_pln_value(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Reason should contain PLN value for NPV objective."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        reason = data.get("recommended_reason", "")

        # Should contain PLN currency reference
        assert "PLN" in reason, f"Reason should mention PLN value: {reason}"

    def test_reason_non_empty_with_custom_objective(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When objective is set, reason should be non-empty."""
        request = {
            **minimal_sizing_request,
            "optimization": {
                "objective": "payback",  # lowercase per OptimizationObjective enum
            }
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        # Check for errors
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:500]}"
        )

        data = response.json()

        # Check variants exist
        variants = data.get("variants", [])
        assert len(variants) > 0, f"Expected variants, got: {list(data.keys())}"

        reason = data.get("recommended_reason")

        # Should have a non-empty reason
        assert reason is not None, (
            f"recommended_reason should be present. "
            f"Response keys: {list(data.keys())}"
        )
        assert isinstance(reason, str), "recommended_reason should be string"
        assert len(reason) > 0, f"recommended_reason should be non-empty: {reason}"


class TestRecommendedReasonWithConstraints:
    """Test that constraints are reflected in recommended_reason."""

    def test_reason_non_empty_with_constraints(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When hard constraints are applied, reason should be non-empty."""
        request = {
            **minimal_sizing_request,
            "optimization": {
                "objective": "npv",  # lowercase per OptimizationObjective enum
                "constraints": [
                    {
                        "constraint_type": "max_payback",  # lowercase per ConstraintType enum
                        "value": 10.0,
                        "hard": True,
                    }
                ]
            }
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        reason = data.get("recommended_reason")

        # Should have a non-empty reason
        assert reason is not None, "recommended_reason should be present"
        assert isinstance(reason, str), "recommended_reason should be string"
        assert len(reason) > 0, f"recommended_reason should be non-empty: {reason}"
