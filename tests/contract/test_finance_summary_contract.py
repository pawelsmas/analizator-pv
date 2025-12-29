"""
Contract tests for finance_summary and finance_assumptions fields.

These tests verify the v0.5.0 finance features:
1. finance_assumptions is present at response level
2. finance_summary is present per variant
3. npv_pln in finance_summary matches top_variants_details[].npv_pln
"""
import pytest
import requests


class TestFinanceAssumptionsPresence:
    """Test that finance_assumptions is present in response."""

    def test_finance_assumptions_present_by_default(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_assumptions should be present even without explicit finance_config."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        assert "finance_assumptions" in data, "finance_assumptions should be in response"
        fa = data["finance_assumptions"]
        assert fa is not None, "finance_assumptions should not be null"

    def test_finance_assumptions_has_required_fields(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_assumptions should have all required fields."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        fa = data["finance_assumptions"]
        required_fields = [
            "horizon_years",
            "discount_rate",
            "savings_escalation_rate",
            "opex_pln_per_year",
            "opex_escalation_rate",
        ]

        for field in required_fields:
            assert field in fa, f"finance_assumptions should have {field}"

    def test_finance_assumptions_defaults_match_request(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_assumptions should reflect request values when no finance_config."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        fa = data["finance_assumptions"]

        # Should use defaults from request
        assert fa["horizon_years"] == minimal_sizing_request.get("analysis_years", 15)
        assert fa["discount_rate"] == minimal_sizing_request.get("discount_rate", 0.08)
        assert fa["savings_escalation_rate"] == 0.0  # Default
        assert fa["opex_pln_per_year"] == 0.0  # Default


class TestFinanceSummaryPresence:
    """Test that finance_summary is present per variant."""

    def test_finance_summary_present_per_variant(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Each variant should have finance_summary."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        assert len(variants) > 0, "Should have at least one variant"

        for v in variants:
            assert "finance_summary" in v, (
                f"Variant {v.get('variant')} should have finance_summary"
            )
            assert v["finance_summary"] is not None, (
                f"Variant {v.get('variant')} finance_summary should not be null"
            )

    def test_finance_summary_has_required_fields(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_summary should have all required fields."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        required_fields = [
            "capex_pln",
            "opex_pln_per_year",
            "horizon_years",
            "discount_rate",
            "npv_pln",
            "payback_years",
        ]

        for v in variants:
            fs = v["finance_summary"]
            for field in required_fields:
                assert field in fs, (
                    f"Variant {v.get('variant')} finance_summary should have {field}"
                )


class TestFinanceSummaryNPVConsistency:
    """Test that NPV is consistent across response."""

    def test_finance_summary_npv_matches_variant_npv(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_summary.npv_pln should match variant.npv_pln."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v["finance_summary"]
            assert abs(fs["npv_pln"] - v["npv_pln"]) < 1.0, (
                f"Variant {v.get('variant')}: finance_summary.npv_pln ({fs['npv_pln']}) "
                f"should match variant.npv_pln ({v['npv_pln']})"
            )

    def test_finance_summary_npv_matches_top_variants_details(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_summary.npv_pln should match top_variants_details[].npv_pln."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Build lookup from variants
        variants = data.get("variants", [])
        variant_npv = {v["variant"]: v["finance_summary"]["npv_pln"] for v in variants}

        # Check top_variants_details
        top_details = data.get("top_variants_details", [])
        for td in top_details:
            variant_name = td["variant"]
            expected_npv = variant_npv.get(variant_name)

            if expected_npv is not None:
                assert abs(td["npv_pln"] - expected_npv) < 1.0, (
                    f"top_variants_details[{variant_name}].npv_pln ({td['npv_pln']}) "
                    f"should match finance_summary.npv_pln ({expected_npv})"
                )


class TestFinanceConfigOverride:
    """Test that finance_config overrides default values."""

    def test_finance_config_horizon_override(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_config.horizon_years should override analysis_years."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "horizon_years": 20,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # finance_assumptions should reflect the override
        fa = data["finance_assumptions"]
        assert fa["horizon_years"] == 20, (
            f"finance_assumptions.horizon_years should be 20, got {fa['horizon_years']}"
        )

        # Each variant's finance_summary should also reflect the override
        for v in data.get("variants", []):
            fs = v["finance_summary"]
            assert fs["horizon_years"] == 20, (
                f"Variant {v.get('variant')} finance_summary.horizon_years "
                f"should be 20, got {fs['horizon_years']}"
            )

    def test_finance_config_discount_rate_override(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """finance_config.discount_rate should override request.discount_rate."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate": 0.12,  # 12%
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        fa = data["finance_assumptions"]
        assert abs(fa["discount_rate"] - 0.12) < 0.001, (
            f"finance_assumptions.discount_rate should be 0.12, got {fa['discount_rate']}"
        )

        for v in data.get("variants", []):
            fs = v["finance_summary"]
            assert abs(fs["discount_rate"] - 0.12) < 0.001, (
                f"Variant {v.get('variant')} finance_summary.discount_rate "
                f"should be 0.12, got {fs['discount_rate']}"
            )
