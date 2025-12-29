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

    def test_reason_mentions_payback_when_objective_is_payback(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When objective is PAYBACK, reason should mention payback period."""
        request = {
            **minimal_sizing_request,
            "optimization": {
                "objective": "PAYBACK",
            }
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        reason = data.get("recommended_reason", "")

        # Should mention payback (Polish: okres zwrotu or lat)
        assert "lat" in reason or "zwrot" in reason, (
            f"Reason should mention payback period: {reason}"
        )


class TestRecommendedReasonWithConstraints:
    """Test that constraints are reflected in recommended_reason."""

    def test_reason_mentions_constraint_when_applied(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When hard constraints are applied, reason should mention them."""
        request = {
            **minimal_sizing_request,
            "optimization": {
                "objective": "NPV",
                "constraints": [
                    {
                        "constraint_type": "MAX_PAYBACK",
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
        reason = data.get("recommended_reason", "")

        # Should mention constraints (Polish: ograniczeniach)
        assert "ograniczeni" in reason.lower() or "payback" in reason.lower(), (
            f"Reason should mention constraints: {reason}"
        )
