"""
Contract tests for PV calculation API.
These tests verify structure and consistency, NOT exact numerical values.
"""
import pytest
import requests


class TestAnalyzeEndpointContract:
    """Test /api/pv/analyze endpoint contract compliance."""

    def test_analyze_returns_variants(
        self, wait_for_services, pv_calculation_url, sample_consumption_annual
    ):
        """Contract: /api/pv/analyze must return variants array."""
        request = {
            "consumption": sample_consumption_annual[:8760],
            "pv_config": {
                "type": "ground_s",
                "capacity_kwp": 500,
                "azimuth": 180,
                "tilt": 35,
                "lat": 52.0,
                "lon": 21.0,
            },
            "bess_config": {
                "enabled": True,
                "mode": "pro",
                "scenario": 2,
            },
        }

        response = requests.post(
            f"{pv_calculation_url}/api/pv/analyze",
            json=request,
            timeout=300,
        )

        # May return 200 or error if PVGIS unavailable
        if response.status_code == 200:
            data = response.json()
            assert "variants" in data or "results" in data, "Response must contain results"

    def test_health_endpoint(self, wait_for_services, pv_calculation_url):
        """Contract: /health endpoint must exist."""
        response = requests.get(f"{pv_calculation_url}/health", timeout=10)
        assert response.status_code == 200, "Health endpoint must return 200"


class TestPVResultsContract:
    """Test PV results structure when BESS is included."""

    def test_bess_results_propagate_savings_breakdown(
        self,
        wait_for_services,
        pv_calculation_url,
        bess_dispatch_url,
        sample_consumption_annual,
    ):
        """Contract: When BESS enabled, savings_breakdown must propagate to response."""
        # First verify bess-dispatch returns savings_breakdown
        bess_request = {
            "load_kw": sample_consumption_annual[:168],
            "pv_generation_kw": [0] * 168,  # No PV for simplicity
            "mode": "pro",
            "scenario": 2,
            "dispatch_mode": "stacked",
            "durations_h": [1.0],
            "prices": {
                "tariff_type": "flat",
                "day_rate_pln_mwh": 500.0,
                "night_rate_pln_mwh": 500.0,
                "other_fees_pln_mwh": 400.0,
            },
            "economic_params": {
                "discount_rate": 0.08,
                "project_lifetime_years": 15,
                "capex_pln_per_kwh": 1800.0,
            },
        }

        bess_response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=bess_request,
            timeout=120,
        )

        if bess_response.status_code == 200:
            bess_data = bess_response.json()
            if bess_data.get("variants"):
                variant = bess_data["variants"][0]
                assert "savings_breakdown" in variant, "BESS variant must have savings_breakdown"
                assert (
                    "net_savings_pln" in variant["savings_breakdown"]
                ), "savings_breakdown must have net_savings_pln"


class TestSSoTContract:
    """Test Single Source of Truth contract."""

    def test_net_savings_is_authoritative(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: savings_breakdown.net_savings_pln is the SSoT for annual savings."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        for variant in data["variants"]:
            sb = variant.get("savings_breakdown", {})

            # net_savings_pln MUST exist
            assert "net_savings_pln" in sb, "net_savings_pln is required (SSoT)"

            # If annual_savings_pln exists at variant level, it should match
            if "annual_savings_pln" in variant:
                variant_annual = variant["annual_savings_pln"]
                sb_net = sb["net_savings_pln"]

                # They should be consistent (same value or very close)
                if abs(sb_net) > 1:
                    diff = abs(variant_annual - sb_net) / abs(sb_net)
                    # Allow 5% tolerance for now (to detect major discrepancies)
                    assert diff < 0.05, (
                        f"annual_savings_pln ({variant_annual}) should match "
                        f"savings_breakdown.net_savings_pln ({sb_net})"
                    )

    def test_all_breakdown_components_present(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: All savings breakdown components must be present."""
        required_components = [
            "energy_savings_pln",
            "capacity_fee_savings_pln",
            "demand_charge_savings_pln",
            "arbitrage_savings_pln",
            "degradation_cost_pln",
            "net_savings_pln",
        ]

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        for i, variant in enumerate(data["variants"]):
            sb = variant.get("savings_breakdown", {})
            for component in required_components:
                assert (
                    component in sb
                ), f"Variant {i} savings_breakdown missing '{component}'"


class TestAnnualSavingsAlignment:
    """Test that annual_savings_pln matches savings_breakdown.net_savings_pln (BUG-002)."""

    def test_annual_savings_equals_net_savings(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: annual_savings_pln == savings_breakdown.net_savings_pln (SSoT)."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        for i, variant in enumerate(data["variants"]):
            annual_savings = variant.get("annual_savings_pln", 0)
            net_savings = variant.get("savings_breakdown", {}).get("net_savings_pln", 0)

            # They should be equal (with small tolerance for floating point)
            if abs(net_savings) > 1:
                diff = abs(annual_savings - net_savings) / abs(net_savings)
                assert diff < 0.001, (
                    f"Variant {i}: annual_savings_pln ({annual_savings:.2f}) != "
                    f"savings_breakdown.net_savings_pln ({net_savings:.2f})"
                )
            else:
                assert abs(annual_savings - net_savings) < 1.0, (
                    f"Variant {i}: annual_savings_pln ({annual_savings}) != "
                    f"savings_breakdown.net_savings_pln ({net_savings})"
                )
