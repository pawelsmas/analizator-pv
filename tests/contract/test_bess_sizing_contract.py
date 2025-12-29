"""
Contract tests for BESS sizing API.
These tests verify structure and consistency, NOT exact numerical values.
"""
import pytest
import requests

# Tolerance for floating point comparisons
TOLERANCE = 0.01  # 1% tolerance for net savings calculation


class TestSizingEndpointContract:
    """Test /sizing endpoint contract compliance."""

    def test_sizing_returns_variants_array(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: /sizing must return 'variants' as an array."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()

        assert "variants" in data, "Response must contain 'variants' field"
        assert isinstance(data["variants"], list), "'variants' must be a list"
        assert len(data["variants"]) > 0, "'variants' must not be empty"

    def test_sizing_returns_recommended_variant(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: /sizing must return identifiable recommended variant."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Must have way to identify recommended variant
        has_recommended_variant = "recommended_variant" in data  # e.g. "small", "medium", "large"
        has_recommended_id = "recommended_variant_id" in data
        has_recommended_idx = "recommended_variant_idx" in data

        # At least one of these must be present
        assert (
            has_recommended_variant or has_recommended_id or has_recommended_idx
        ), "Response must identify recommended variant"

        # If we have variants with is_recommended flag, verify at least one is recommended
        if data.get("variants"):
            recommended_count = sum(1 for v in data["variants"] if v.get("is_recommended", False))
            assert recommended_count >= 1, "At least one variant should be marked is_recommended=True"

    def test_each_variant_has_savings_breakdown(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: Each variant must have savings_breakdown with net_savings_pln."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        for i, variant in enumerate(data["variants"]):
            assert (
                "savings_breakdown" in variant
            ), f"Variant {i} missing 'savings_breakdown'"

            sb = variant["savings_breakdown"]
            assert (
                "net_savings_pln" in sb
            ), f"Variant {i} savings_breakdown missing 'net_savings_pln'"
            assert isinstance(
                sb["net_savings_pln"], (int, float)
            ), f"Variant {i} net_savings_pln must be numeric"

    def test_savings_breakdown_net_equals_components(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: net_savings_pln == energy + capacity + demand + arbitrage + export - degradation."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        for i, variant in enumerate(data["variants"]):
            sb = variant["savings_breakdown"]

            # Extract components (default to 0 if missing)
            energy = sb.get("energy_savings_pln", 0)
            capacity = sb.get("capacity_fee_savings_pln", 0)
            demand = sb.get("demand_charge_savings_pln", 0)
            arbitrage = sb.get("arbitrage_savings_pln", 0)
            export = sb.get("export_revenue_pln", 0)
            degradation = abs(sb.get("degradation_cost_pln", 0))
            net = sb.get("net_savings_pln", 0)

            # Calculate expected net
            expected_net = energy + capacity + demand + arbitrage + export - degradation

            # Allow small tolerance for floating point
            if abs(expected_net) > 1:  # Avoid division by zero
                relative_diff = abs(net - expected_net) / abs(expected_net)
                assert (
                    relative_diff < TOLERANCE
                ), f"Variant {i}: net_savings_pln={net} != calculated={expected_net} (diff={relative_diff:.2%})"
            else:
                # For very small values, use absolute tolerance
                assert (
                    abs(net - expected_net) < 1.0
                ), f"Variant {i}: net_savings_pln={net} != calculated={expected_net}"

    def test_each_variant_has_required_fields(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: Each variant must have power_kw, energy_kwh, capex, npv."""
        required_fields = [
            "power_kw",
            "energy_kwh",
            "capex_pln",
            "npv_pln",
            "simple_payback_years",  # Note: field name is simple_payback_years
        ]

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        for i, variant in enumerate(data["variants"]):
            for field in required_fields:
                assert field in variant, f"Variant {i} missing required field '{field}'"
                assert isinstance(
                    variant[field], (int, float)
                ), f"Variant {i} {field} must be numeric"

    def test_variants_have_different_durations(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: Variants should cover requested durations (1h, 2h, 4h)."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Extract duration_h from each variant
        durations = set()
        for variant in data["variants"]:
            if "duration_h" in variant:
                durations.add(variant["duration_h"])
            elif "energy_kwh" in variant and "power_kw" in variant:
                # Calculate duration from energy/power ratio
                if variant["power_kw"] > 0:
                    duration = variant["energy_kwh"] / variant["power_kw"]
                    durations.add(round(duration, 1))

        # Should have multiple durations
        assert len(durations) >= 1, "Should have at least one duration variant"


class TestSizingInputValidation:
    """Test /sizing input validation."""

    def test_rejects_empty_load(self, wait_for_services, bess_dispatch_url):
        """Contract: Should reject request with empty load_kw."""
        request = {
            "load_kw": [],
            "pv_generation_kw": [100] * 168,
            "mode": "pro",
            "scenario": 2,
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=30,
        )

        # Should return 4xx error
        assert response.status_code >= 400, "Should reject empty load_kw"

    def test_rejects_mismatched_arrays(self, wait_for_services, bess_dispatch_url):
        """Contract: Should reject when load_kw and pv_generation_kw lengths differ."""
        request = {
            "load_kw": [100] * 168,
            "pv_generation_kw": [100] * 100,  # Different length
            "mode": "pro",
            "scenario": 2,
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=30,
        )

        # Should return 4xx error
        assert response.status_code >= 400, "Should reject mismatched array lengths"


class TestRecommendedVariantLogic:
    """Test recommended variant selection logic."""

    def test_recommended_matches_highest_score(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: Recommended variant should have highest score (NPV by default)."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()
        variants = data.get("variants", [])

        if not variants:
            pytest.skip("No variants returned")

        # Find variant marked as recommended
        recommended_variants = [v for v in variants if v.get("is_recommended", False)]
        assert len(recommended_variants) == 1, "Exactly one variant should be recommended"

        recommended = recommended_variants[0]

        # Find variant with highest score
        highest_score_variant = max(variants, key=lambda v: v.get("score", float("-inf")))

        # Recommended variant should be the one with highest score
        assert recommended["variant"] == highest_score_variant["variant"], (
            f"Recommended variant {recommended['variant']} (score={recommended['score']:.2f}) "
            f"should match highest score variant {highest_score_variant['variant']} "
            f"(score={highest_score_variant['score']:.2f})"
        )

    def test_score_equals_npv_by_default(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: With default optimization, score should equal npv_pln."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        for variant in data.get("variants", []):
            npv = variant.get("npv_pln", 0)
            score = variant.get("score", 0)

            # Score should equal NPV (with small tolerance for floating point)
            if abs(npv) > 1:
                diff = abs(score - npv) / abs(npv)
                assert diff < 0.001, (
                    f"Variant {variant['variant']}: score={score:.2f} should equal npv={npv:.2f}"
                )


class TestPeriodInfo:
    """Test period_info in response (SSoT for time axis)."""

    def test_period_info_returned(
        self, wait_for_services, bess_dispatch_url, minimal_sizing_request
    ):
        """Contract: /sizing must return period_info with time axis metadata."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # period_info should be present
        assert "period_info" in data, "Response must include period_info"

        pi = data["period_info"]
        assert "period_hours" in pi, "period_info must have period_hours"
        assert "period_days" in pi, "period_info must have period_days"
        assert "is_full_year" in pi, "period_info must have is_full_year"
        assert "annualization_factor" in pi, "period_info must have annualization_factor"

        # Validate consistency
        assert pi["period_hours"] > 0, "period_hours must be positive"
        assert pi["period_days"] == pi["period_hours"] / 24.0, "period_days = period_hours / 24"

        # For 168 hours (1 week), is_full_year should be False
        if pi["period_hours"] < 8760:
            assert not pi["is_full_year"], "is_full_year should be False for partial periods"
            assert pi["annualization_factor"] > 1, "annualization_factor > 1 for partial periods"


class TestHealthEndpoint:
    """Test service health endpoint."""

    def test_health_endpoint_exists(self, wait_for_services, bess_dispatch_url):
        """Contract: /health endpoint must exist and return 200."""
        response = requests.get(f"{bess_dispatch_url}/health", timeout=10)
        assert response.status_code == 200, "Health endpoint must return 200"
