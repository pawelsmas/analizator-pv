"""
Contract tests for applied_parameters field in sizing response.

These tests verify:
- applied_parameters is present in response
- All required fields are populated
- degradation_cost_source correctly reflects the source
- Default values are documented
"""
import pytest
import requests


class TestAppliedParametersPresence:
    """Test that applied_parameters is present and has required fields."""

    def test_applied_parameters_present_in_response(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """applied_parameters should always be present in sizing response."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        assert "applied_parameters" in data, "applied_parameters must be in response"
        assert data["applied_parameters"] is not None, "applied_parameters cannot be null"

    def test_applied_parameters_has_required_fields(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """applied_parameters must have all required fields."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        params = data["applied_parameters"]

        required_fields = [
            "degradation_cost_pln_mwh",
            "degradation_cost_source",
            "discount_rate",
            "analysis_years",
            "opex_pct_per_year",
            "import_price_pln_mwh",
            "export_price_pln_mwh",
        ]

        for field in required_fields:
            assert field in params, f"Missing required field: {field}"


class TestDegradationCostSource:
    """Test degradation_cost_source reflects correct source."""

    def test_default_source_when_not_specified(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When no degradation_cost_pln_mwh specified, source should be 'default'."""
        # Minimal request doesn't specify degradation_cost_pln_mwh
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        params = data["applied_parameters"]

        assert params["degradation_cost_source"] == "default"
        assert params["degradation_cost_pln_mwh"] == 50.0  # Default value

    def test_request_source_when_explicitly_set(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When degradation_cost_pln_mwh is explicitly set, source should be 'request'."""
        request = {**minimal_sizing_request, "degradation_cost_pln_mwh": 75.0}

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        params = data["applied_parameters"]

        assert params["degradation_cost_source"] == "request"
        assert params["degradation_cost_pln_mwh"] == 75.0

    def test_zero_degradation_cost_is_valid(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """degradation_cost_pln_mwh=0 should disable degradation cost."""
        request = {**minimal_sizing_request, "degradation_cost_pln_mwh": 0.0}

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        params = data["applied_parameters"]

        assert params["degradation_cost_pln_mwh"] == 0.0
        # Source is 'request' because 0 != 50 (default)
        assert params["degradation_cost_source"] == "request"


class TestAppliedParametersValues:
    """Test that applied_parameters values match request."""

    def test_economics_params_match_request(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Economics parameters should match request values."""
        request = {
            **minimal_sizing_request,
            "discount_rate": 0.10,
            "analysis_years": 20,
            "opex_pct_per_year": 0.02,
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        params = data["applied_parameters"]

        assert params["discount_rate"] == 0.10
        assert params["analysis_years"] == 20
        assert params["opex_pct_per_year"] == 0.02

    def test_pricing_params_are_numeric(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Pricing parameters should be numeric and non-negative."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        params = data["applied_parameters"]

        # Import price should be positive (we always have an import price)
        assert isinstance(params["import_price_pln_mwh"], (int, float))
        assert params["import_price_pln_mwh"] >= 0

        # Export price can be zero (no export configured)
        assert isinstance(params["export_price_pln_mwh"], (int, float))
        assert params["export_price_pln_mwh"] >= 0
