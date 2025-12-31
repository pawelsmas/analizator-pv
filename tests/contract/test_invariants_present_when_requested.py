"""
Contract tests for invariants report feature (v1.6.0).

Verifies that:
- include_invariants=True returns invariants block in variants
- Invariants contain expected boolean fields
- Invariants are absent when not requested (default)
"""

import pytest
from ._api import post_json, pick_recommended_variant, load_smoke_payload


class TestInvariantsPresent:
    """Tests for invariants in sizing response."""

    def test_invariants_present_when_requested(self):
        """
        When include_invariants=True, each variant should have invariants block.
        """
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_invariants"] = True

        resp = post_json("/sizing", payload)

        # Verify variants exist
        assert "variants" in resp, "Response should have variants"
        assert len(resp["variants"]) > 0, "Should have at least one variant"

        # Check each variant has invariants
        for variant in resp["variants"]:
            assert "invariants" in variant, f"Variant should have invariants block"
            invariants = variant["invariants"]

            # Check expected fields exist
            assert "energy_balance_ok" in invariants
            assert "non_negative_ok" in invariants
            assert "cost_sums_ok" in invariants
            assert "annualization_ok" in invariants
            assert "all_passed" in invariants

            # Values should be booleans
            assert isinstance(invariants["energy_balance_ok"], bool)
            assert isinstance(invariants["non_negative_ok"], bool)
            assert isinstance(invariants["cost_sums_ok"], bool)
            assert isinstance(invariants["annualization_ok"], bool)
            assert isinstance(invariants["all_passed"], bool)

    def test_invariants_absent_by_default(self):
        """
        When include_invariants is not set (default=False), invariants should be null/absent.
        """
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        # Do NOT set include_invariants

        resp = post_json("/sizing", payload)

        assert "variants" in resp
        for variant in resp["variants"]:
            # invariants should be None or not present
            invariants = variant.get("invariants")
            assert invariants is None, "Invariants should be None when not requested"

    def test_invariants_all_passed_true_for_valid_result(self):
        """
        For a valid sizing result, all_passed should be True.
        """
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_invariants"] = True

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        invariants = recommended.get("invariants", {})

        # A valid result should pass all invariants
        assert invariants.get("all_passed") is True, (
            f"Expected all_passed=True, got invariants: {invariants}"
        )

    def test_invariants_have_max_abs_error_fields(self):
        """
        Invariants may include max_abs_error fields for numeric checks.
        """
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_invariants"] = True

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        invariants = recommended.get("invariants", {})

        # Check for error magnitude fields (present when > 0)
        # These are optional but if present should be floats
        for key in invariants:
            if "max_abs_error" in key:
                assert isinstance(invariants[key], (int, float)), (
                    f"{key} should be numeric"
                )


class TestInvariantsWithArbitrage:
    """Test invariants with arbitrage scenarios."""

    def test_invariants_with_arbitrage_config(self):
        """
        Invariants should work with arbitrage configuration.
        """
        payload = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        payload["include_invariants"] = True

        resp = post_json("/sizing", payload)

        assert len(resp["variants"]) > 0

        for variant in resp["variants"]:
            assert "invariants" in variant
            # All should pass for valid results
            assert variant["invariants"]["all_passed"] is True
